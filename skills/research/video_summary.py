"""Video summarization via a transcript provider adapter (stdlib core).

The real work — fetching a transcript — goes through the
``TranscriptProvider`` Protocol. The bundled stub fails honestly. The
``summarize_text`` pure function is a reusable extractive summarizer:
sentence scoring by word frequency with a position bonus.
"""

from __future__ import annotations

import re
from typing import Protocol

from skills.base import Skill, SkillContext, SkillError

_URL_RE = re.compile(r"https?://[^\s<>\")']+")

_STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because
    been before being below between both but by can did do does doing down
    during each few for from further had has have having he her here hers
    herself him himself his how i if in into is it its itself just like me
    more most my myself no nor not now of off on once only or other ought our
    ours ourselves out over own same she should so some such than that the
    their theirs them themselves then there these they this those through to
    too under until up very was we were what when where which while who whom
    why with would you your yours yourself yourselves
    """.split()
)


class TranscriptProvider(Protocol):
    """Plug-in point for a real transcript source (e.g. caption APIs)."""

    def fetch_transcript(self, url: str) -> str:
        """Return the plain-text transcript for a video ``url`` or raise."""
        ...


class UnconfiguredTranscriptProvider:
    """Ships with the skill; fails honestly instead of inventing a summary."""

    def fetch_transcript(self, url: str) -> str:
        raise SkillError(
            "no transcript provider configured — plug a TranscriptProvider "
            "into VideoSummarySkill to summarize videos"
        )


def _sentences(text: str) -> list[str]:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", collapsed) if s.strip()]


def _content_words(sentence: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{3,}", sentence.lower()) if w not in _STOPWORDS]


def summarize_text(text: str, n: int = 5) -> list[str]:
    """Extractive summary: top-``n`` sentences by word-frequency + position bonus.

    Pure function — reusable anywhere a quick extractive summary is needed.
    """
    sentences = _sentences(text)
    if len(sentences) <= n:
        return sentences
    freq: dict[str, int] = {}
    for sentence in sentences:
        for word in _content_words(sentence):
            freq[word] = freq.get(word, 0) + 1
    total = len(sentences)
    scored: list[tuple[float, int]] = []
    for i, sentence in enumerate(sentences):
        words = _content_words(sentence)
        base = sum(freq.get(w, 0) for w in words) / max(len(words), 1)
        bonus = (total - i) / total  # earlier sentences get a small boost
        scored.append((base + bonus, i))
    top = sorted(sorted(scored, reverse=True)[:n], key=lambda item: item[1])
    return [sentences[i] for _, i in top]


class VideoSummarySkill(Skill):
    """Summarizes a video via its transcript provider."""

    name = "video_summary"
    description = (
        "Fetches a video transcript through a plugged TranscriptProvider "
        "and returns an extractive summary (frequency-scored sentences)."
    )
    intents = ("video.summarize",)
    required_capabilities = ("skills.execute", "network.fetch")
    background = True
    local_only = False
    adapter_note = (
        "Transcript fetching needs a TranscriptProvider attached via "
        "VideoSummarySkill(provider=...). Without one, the skill reports "
        "not-configured instead of inventing a summary."
    )

    def __init__(self, provider: TranscriptProvider | None = None) -> None:
        self._provider: TranscriptProvider = provider or UnconfiguredTranscriptProvider()

    def set_provider(self, provider: TranscriptProvider) -> None:
        """Attach a real transcript provider implementation."""
        self._provider = provider

    async def handle(self, context: SkillContext) -> str:
        match = _URL_RE.search(context.message)
        if not match:
            return "usage: summarize <video url> (needs a configured transcript provider)"
        url = match.group(0)
        try:
            transcript = self._provider.fetch_transcript(url)
        except SkillError as exc:
            return f"cannot summarize {url}: {exc}"
        if not transcript.strip():
            return f"empty transcript for {url} — nothing to summarize"
        points = summarize_text(transcript)
        lines = [f"Summary of {url}:", ""]
        lines.extend(f"{i + 1}. {point}" for i, point in enumerate(points))
        return "\n".join(lines)


SKILLS: list[Skill] = [VideoSummarySkill()]
