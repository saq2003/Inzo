"""Research engine: pluggable fetch + local extractive summarizer.

Web fetching is behind a ``Fetcher`` protocol (Rule 6) so INZO works fully
offline with ``NullFetcher`` and gains live research when a fetcher is
wired in. Summarization is local and deterministic.
"""

from __future__ import annotations

import re
from typing import Protocol

from app.logging_config import get_logger

logger = get_logger(__name__)


class FetchError(Exception):
    """Raised when a fetch fails (network, timeout, blocked)."""


class Fetcher(Protocol):
    """Pluggable web fetcher (Rule 6)."""

    name: str

    async def fetch(self, url: str, *, timeout_s: float = 20.0) -> str:
        """Return page text for ``url``. Must honor ``timeout_s`` (Rule 9)."""
        ...


class NullFetcher:
    """Offline default: research requires an explicit fetcher to be wired."""

    name = "null"

    async def fetch(self, url: str, *, timeout_s: float = 20.0) -> str:
        raise FetchError(
            "no web fetcher configured; wire a Fetcher to enable live research"
        )


_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]")


def summarize(text: str, max_sentences: int = 3) -> str:
    """Extractive summary: first ``max_sentences`` sentences (deterministic)."""
    sentences = [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]
    return " ".join(sentences[:max_sentences])


class ResearchEngine:
    """Coordinates fetch -> summarize research tasks."""

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or NullFetcher()

    async def research(self, topic: str, urls: list[str]) -> dict[str, str]:
        """Fetch each URL and return {url: summary} (failures recorded)."""
        results: dict[str, str] = {}
        for url in urls:
            try:
                page = await self.fetcher.fetch(url, timeout_s=20.0)
                results[url] = summarize(page)
            except FetchError as exc:
                results[url] = f"fetch failed: {exc}"
        logger.info("research complete", extra={"topic": topic, "urls": len(urls)})
        return results

    def summarize_local(self, text: str, max_sentences: int = 3) -> str:
        """Summarize already-held text without any network."""
        return summarize(text, max_sentences=max_sentences)
