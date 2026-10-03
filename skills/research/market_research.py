"""Market research brief builder: structured sections from fetched sources.

"market <product/idea>" (or "research market for <...>") gathers up to
4 pages — seed URLs from the message plus a public Wikipedia search —
then synthesizes a brief with Overview/Audience/Competitors/Pricing/
Channels/Risks sections. Every section cites its sources [n]; sections
with no evidence say so honestly instead of inventing content.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import urlencode, urlparse

from skills.base import Skill, SkillContext

_MAX_PAGES = 4
_URL_RE = re.compile(r"https?://[^\s<>\")']+")
_WIKI_API = "https://en.wikipedia.org/w/api.php"

_SECTION_RULES: tuple[tuple[str, str], ...] = (
    ("Audience", r"customer|user|demographic|audience|buyer|consumer|client"),
    ("Competitors", r"competitor|rival|alternative|compete|market share|incumbent"),
    ("Pricing", r"price|cost|pricing|subscription|freemium|\$"),
    ("Channels", r"channel|distribution|retail|online|partner|marketing|advertis"),
    ("Risks", r"risk|challenge|threat|regulation|barrier|downside"),
)


async def _fetch(url: str, *, timeout: float = 8.0, retries: int = 2) -> str | None:
    """Fetch ``url`` with bounded retries; return decoded text or None."""
    if urlparse(url).scheme.lower() not in ("http", "https"):
        return None
    request = urllib.request.Request(  # noqa: S310 — scheme allowlisted to http/https above
        url, headers={"User-Agent": "inzo-research/0.1"}
    )
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw_bytes = cast("bytes", response.read())
                return raw_bytes.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — network is unreliable; retry, then give up
            attempt += 1
            if attempt > retries:
                return None
            await asyncio.sleep(min(2.0**attempt, 4.0))


class _TextExtractor(HTMLParser):
    """Collects visible text; skips script/style."""

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            text = data.strip()
            if text:
                self.chunks.append(text)

    def text(self) -> str:
        """Collapsed visible text."""
        return re.sub(r"\s+", " ", " ".join(self.chunks)).strip()


@dataclass
class _Page:
    url: str
    text: str


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 25]


async def _wiki_search(query: str, limit: int = 3) -> list[str]:
    """Public Wikipedia search for seed article URLs."""
    params = urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(limit),
            "format": "json",
        }
    )
    raw = await _fetch(f"{_WIKI_API}?{params}")
    if raw is None:
        return []
    try:
        data = cast("dict[str, Any]", json.loads(raw))
    except json.JSONDecodeError:
        return []
    query_obj = cast("dict[str, Any]", data.get("query") or {})
    urls: list[str] = []
    for item in cast("list[Any]", query_obj.get("search") or []):
        if isinstance(item, dict):
            title = str(item.get("title", "")).strip()
            if title:
                urls.append("https://en.wikipedia.org/wiki/" + title.replace(" ", "_"))
    return urls


def _section_sentences(pages: list[_Page], pattern: str) -> list[tuple[str, int]]:
    """(sentence, page_index) pairs matching the section pattern, best first."""
    regex = re.compile(pattern, re.IGNORECASE)
    found: list[tuple[str, int]] = []
    for idx, page in enumerate(pages):
        for sentence in _sentences(page.text):
            hits = len(regex.findall(sentence))
            if hits:
                found.append((sentence, idx))
                if len(found) >= 12:
                    break
    found.sort(key=lambda item: len(regex.findall(item[0])), reverse=True)
    return found[:2]


class MarketResearchSkill(Skill):
    """Builds a structured, cited market brief from fetched sources."""

    name = "market_research"
    description = (
        "Builds a market brief (Overview/Audience/Competitors/Pricing/"
        "Channels/Risks) from up to 4 fetched pages, with citations."
    )
    intents = ("research.market",)
    required_capabilities = ("skills.execute", "network.fetch")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        message = context.message.strip()
        query = message
        for prefix in ("research market for", "market research", "market"):
            if message.lower().startswith(prefix):
                query = message[len(prefix) :].strip(" :")
                break
        query = _URL_RE.sub("", query).strip()
        if not query:
            return "usage: market <product or idea> [optional seed URLs]"
        seeds = _URL_RE.findall(message)
        if not seeds:
            seeds = await _wiki_search(f"{query} market", 3)

        pages: list[_Page] = []
        for url in seeds[:_MAX_PAGES]:
            raw = await _fetch(url)
            if raw is None:
                continue
            extractor = _TextExtractor()
            extractor.feed(raw)
            text = extractor.text()
            if text:
                pages.append(_Page(url=url, text=text[:6000]))
        if not pages:
            return f"market research failed: no pages could be fetched for {query!r}"

        lines = [f"Market brief: {query}", "", "Overview"]
        overview = " ".join(_sentences(pages[0].text)[:2])
        lines.append(f"{overview or '(no overview found)'} [1]")
        for section, pattern in _SECTION_RULES:
            lines.extend(["", section])
            matches = _section_sentences(pages, pattern)
            if not matches:
                lines.append("(no evidence in fetched sources)")
            else:
                lines.extend(f"- {sentence} [{idx + 1}]" for sentence, idx in matches)
        lines.extend(["", "Sources:"])
        lines.extend(f"[{i}] {page.url}" for i, page in enumerate(pages, 1))
        return "\n".join(lines)


SKILLS: list[Skill] = [MarketResearchSkill()]
