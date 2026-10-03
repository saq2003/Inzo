"""Extractive conversation summarizer (no model needed).

Real deterministic logic: :func:`summarize` splits text into sentences
with a regex, scores each by word-frequency (stopwords excluded) with a
small position bonus for early sentences, drops near-duplicate
sentences (Jaccard similarity), and returns the top ``max_sentences``
in original order. Summaries persist in ``data_dir/"summaries.db"``.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_STORE_FILE = "summaries.db"
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-z0-9']+")
_DEDUPE_JACCARD = 0.8

_STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all am an and any are as at be because
    been before being below between both but by can cannot could did do does
    doing down during each few for from further had has have having he her
    here hers herself him himself his how i if in into is it its itself just
    like me more most my myself no nor not now of off on once only or other
    ought our ours ourselves out over own same she should so some such than
    that the their theirs them themselves then there these they this those
    through to too under until up very was we were what when where which
    while who whom why with would you your yours yourself yourselves
    """.split()
)


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]
    return parts


def _word_set(sentence: str) -> set[str]:
    return {w for w in _WORD_RE.findall(sentence.lower()) if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def summarize(text: str, max_sentences: int = 5) -> list[str]:
    """Extractive summary: top ``max_sentences`` sentences, original order."""
    sentences = _sentences(text)
    if len(sentences) <= max(1, max_sentences):
        return sentences
    freq: Counter[str] = Counter()
    for sentence in sentences:
        freq.update(_word_set(sentence))
    if not freq:
        return sentences[:max_sentences]
    scored: list[tuple[float, int]] = []
    for i, sentence in enumerate(sentences):
        words = _word_set(sentence)
        if not words:
            scored.append((0.0, i))
            continue
        # Frequency score normalized by sentence length, plus a small
        # position bonus: earlier sentences usually frame the topic.
        score = sum(freq[w] for w in words) / len(words)
        score *= 1.0 + 0.1 * (1.0 - i / len(sentences))
        scored.append((score, i))
    scored.sort(key=lambda item: item[0], reverse=True)
    chosen: list[int] = []
    chosen_sets: list[set[str]] = []
    for _, i in scored:
        words = _word_set(sentences[i])
        if any(_jaccard(words, prev) > _DEDUPE_JACCARD for prev in chosen_sets):
            continue
        chosen.append(i)
        chosen_sets.append(words)
        if len(chosen) >= max_sentences:
            break
    chosen.sort()
    return [sentences[i] for i in chosen]


class ConvSummarizerSkill(Skill):
    """Summarizes conversation text into bullet points."""

    name = "conv_summarizer"
    description = (
        "Extractive summarizer: 'summarize <text>' returns the key "
        "sentences as bullets and stores the summary."
    )
    intents = ("conv.summarize",)
    required_capabilities = ("skills.execute", "memory.write")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        message = context.message.strip()
        lowered = message.lower()
        if lowered.startswith("summarize "):
            text = message[len("summarize ") :].strip()
        elif lowered.startswith("summarize:"):
            text = message.split(":", 1)[1].strip()
        else:
            return "usage: summarize <text to summarize>"
        if not text:
            return "nothing to summarize."
        bullets = summarize(text)
        doc: dict[str, Any] = {
            "source": text[:2000],
            "summary": bullets,
            "created": datetime.now(UTC).isoformat(),
        }
        summary_id = SQLiteDocumentStore(data_dir / _STORE_FILE).add(doc)
        lines = [f"summary (id={summary_id}):"]
        lines.extend(f"- {b}" for b in bullets)
        return "\n".join(lines)


SKILLS: list[Skill] = [ConvSummarizerSkill()]
