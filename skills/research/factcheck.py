"""Fact-check helper: claim extraction + real source comparison (stdlib).

Sentences containing numbers, quoted spans, or superlatives are treated
as checkable claims. A ``SourceChecker`` Protocol compares each claim
against fetched sources; the bundled ``WebSourceChecker`` pulls the top
public Wikipedia articles for the claim's keywords and scores keyword
overlap — a real comparison with honest, heuristic confidence wording.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Protocol, cast
from urllib.parse import urlencode, urlparse

from skills.base import Skill, SkillContext

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_SUPERLATIVES = (
    "biggest|smallest|largest|fastest|slowest|best|worst|first|only|"
    "never|always|none|longest|shortest|highest|lowest|greatest"
)
_CLAIM_RE = re.compile(rf"\b({_SUPERLATIVES})\b", re.IGNORECASE)
_STOPWORDS = frozenset(
    "about after again being between both during each from into more most "
    "other over same such than that their them then there these they this "
    "those under what when where which while with would your".split()
)


async def _fetch(url: str, *, timeout: float = 8.0, retries: int = 2) -> str | None:
    """Fetch ``url`` with bounded retries; return decoded text or None."""
    if urlparse(url).scheme.lower() not in ("http", "https"):
        return None
    request = urllib.request.Request(  # noqa: S310 — scheme allowlisted to http/https above
        url, headers={"User-Agent": "inzo-factcheck/0.1"}
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


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def extract_claims(text: str, limit: int = 3) -> list[str]:
    """Sentences with numbers, quoted spans, or superlatives = checkable claims."""
    claims: list[str] = []
    for sentence in _sentences(text):
        if len(claims) >= limit:
            break
        if re.search(r"\d", sentence) or '"' in sentence or _CLAIM_RE.search(sentence):
            claims.append(sentence)
    return claims


@dataclass
class SourceVerdict:
    """Result of comparing one claim against fetched sources."""

    sources: list[str]
    agreement: float  # 0.0–1.0 keyword overlap across sources
    note: str


class SourceChecker(Protocol):
    """Plug-in point for claim verification backends."""

    async def check(self, claim: str) -> SourceVerdict:
        """Compare ``claim`` against sources; never fabricate evidence."""
        ...


class WebSourceChecker:
    """Compares claim keywords against top public Wikipedia articles."""

    async def check(self, claim: str) -> SourceVerdict:
        keywords = [
            w
            for w in re.findall(r"[a-zA-Z]{5,}", claim.lower())
            if w not in _STOPWORDS
        ][:6]
        if not keywords:
            return SourceVerdict([], 0.0, "no distinctive keywords to check")
        params = urlencode(
            {
                "action": "query",
                "list": "search",
                "srsearch": " ".join(keywords),
                "srlimit": "2",
                "format": "json",
            }
        )
        raw = await _fetch(f"{_WIKI_API}?{params}")
        urls: list[str] = []
        if raw is not None:
            try:
                data = cast("dict[str, Any]", json.loads(raw))
            except json.JSONDecodeError:
                data = {}
            query = cast("dict[str, Any]", data.get("query") or {})
            for item in cast("list[Any]", query.get("search") or []):
                if isinstance(item, dict):
                    title = str(item.get("title", "")).strip()
                    if title:
                        urls.append("https://en.wikipedia.org/wiki/" + title.replace(" ", "_"))
        texts: list[str] = []
        for url in urls:
            page = await _fetch(url)
            if page:
                extractor = _TextExtractor()
                extractor.feed(page)
                texts.append(extractor.text().lower())
        if not texts:
            return SourceVerdict(urls, 0.0, "no source pages could be fetched")
        scores = [
            sum(1 for k in keywords if k in text) / len(keywords) for text in texts
        ]
        agreement = sum(scores) / len(scores)
        return SourceVerdict(urls, agreement, f"{len(texts)} source page(s) compared")


def _verdict_text(verdict: SourceVerdict) -> str:
    if not verdict.sources:
        return f"unverifiable — {verdict.note} (low confidence)"
    if verdict.agreement >= 0.6:
        level = "likely supported"
    elif verdict.agreement >= 0.35:
        level = "mixed evidence"
    else:
        level = "not supported by fetched sources"
    return f"{level} (heuristic confidence; {verdict.note})"


class FactCheckSkill(Skill):
    """Extracts checkable claims and compares them against fetched sources."""

    name = "factcheck"
    description = (
        "Extracts checkable claims (numbers, quotes, superlatives) from "
        "text and compares each against fetched sources with honest "
        "confidence wording."
    )
    intents = ("fact.check",)
    required_capabilities = ("skills.execute", "network.fetch")
    background = True
    local_only = True

    def __init__(self, checker: SourceChecker | None = None) -> None:
        self._checker: SourceChecker = checker or WebSourceChecker()

    def set_checker(self, checker: SourceChecker) -> None:
        """Attach a different claim-verification backend."""
        self._checker = checker

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        for prefix in ("factcheck", "fact check", "check"):
            if text.lower().startswith(prefix):
                text = text[len(prefix) :].strip()
                break
        if not text:
            return "usage: factcheck <text containing claims>"
        claims = extract_claims(text)
        if not claims:
            return "no checkable claims found (looks for numbers, quoted spans, superlatives)"
        lines = [f"Fact-check: {len(claims)} checkable claim(s)", ""]
        for i, claim in enumerate(claims, 1):
            verdict = await self._checker.check(claim)
            lines.append(f"Claim {i}: {claim}")
            lines.append(f"Verdict: {_verdict_text(verdict)}")
            if verdict.sources:
                lines.append("Sources: " + ", ".join(verdict.sources))
            lines.append("")
        return "\n".join(lines).rstrip()


SKILLS: list[Skill] = [FactCheckSkill()]
