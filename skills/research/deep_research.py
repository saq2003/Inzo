"""Bounded multi-page web research with citations (stdlib, fully local).

Fetches up to 5 pages (seed URLs from the message, or a public Wikipedia
search fallback), strips them to visible text with an ``html.parser``
subclass, ranks by keyword overlap with the topic, and produces a brief
with numbered [1]..[n] citations plus a source list.
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

_MAX_PAGES = 5
_URL_RE = re.compile(r"https?://[^\s<>\")']+")
_WIKI_API = "https://en.wikipedia.org/w/api.php"


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
    """Collects visible text and outbound http(s) links; skips script/style."""

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value and value.startswith("http"):
                    self.links.append(value)

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
    return [p.strip() for p in parts if len(p.strip()) > 20]


async def _wiki_search(topic: str, limit: int = 5) -> list[str]:
    """Public Wikipedia search fallback when the message carries no URLs."""
    params = urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": topic,
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
    query = cast("dict[str, Any]", data.get("query") or {})
    items = cast("list[Any]", query.get("search") or [])
    urls: list[str] = []
    for item in items:
        if isinstance(item, dict):
            title = str(item.get("title", "")).strip()
            if title:
                urls.append("https://en.wikipedia.org/wiki/" + title.replace(" ", "_"))
    return urls


def _topic_keywords(topic: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", topic)}


def _rank(pages: list[_Page], keywords: set[str]) -> list[_Page]:
    def score(page: _Page) -> int:
        words = set(page.text.lower().split())
        return len(keywords & words)

    return sorted(pages, key=score, reverse=True)


class DeepResearchSkill(Skill):
    """Bounded multi-page research producing a cited brief."""

    name = "deep_research"
    description = (
        "Researches a topic across up to 5 fetched pages (URLs from the "
        "message or Wikipedia search), ranks by keyword overlap, and "
        "returns a brief with numbered citations."
    )
    intents = ("research.deep",)
    required_capabilities = ("skills.execute", "network.fetch")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        message = context.message.strip()
        topic = message
        for prefix in ("deep research", "research"):
            if message.lower().startswith(prefix):
                topic = message[len(prefix) :].strip()
                break
        topic = _URL_RE.sub("", topic).strip()
        if not topic:
            return "usage: research <topic> [optional seed URLs]"
        seeds = _URL_RE.findall(message)
        if not seeds:
            seeds = await _wiki_search(topic, _MAX_PAGES)

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
            return f"research failed: no pages could be fetched for {topic!r}"

        ranked = _rank(pages, _topic_keywords(topic))
        lines = [f"Research brief: {topic}", ""]
        for i, page in enumerate(ranked, 1):
            lines.append(f"[{i}] {page.url}")
            summary = " ".join(_sentences(page.text)[:3])
            lines.append(summary or "(no extractable text)")
            lines.append("")
        lines.append("Sources:")
        lines.extend(f"[{i}] {page.url}" for i, page in enumerate(ranked, 1))
        return "\n".join(lines)


SKILLS: list[Skill] = [DeepResearchSkill()]
