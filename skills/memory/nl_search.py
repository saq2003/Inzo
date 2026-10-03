"""Natural-language memory search skill: time-aware, multi-source search.

Real (deterministic, stdlib): :func:`parse_time_range` turns English/Hinglish
time expressions ("last week", "pichle hafte", "yesterday", "kal", "aaj",
"today", ...) into ISO date ranges; :meth:`MemoryNlSearchSkill.handle`
searches the episodic ``episodes.db`` store and ``context.memory.recall``,
then merges and ranks the hits.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_EPISODES_DB = "episodes.db"

#: (regex, range-in-days) — the matched expression maps to [today-n, today].
_TIME_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\b(today|aaj)\b", re.IGNORECASE), 0),
    (re.compile(r"\b(yesterday|kal)\b", re.IGNORECASE), 1),
    (re.compile(r"\b(last week|pichle hafte|pichhle hafte)\b", re.IGNORECASE), 7),
    (re.compile(r"\b(last month|pichle mahine)\b", re.IGNORECASE), 30),
    (re.compile(r"\blast\s+(\d+)\s+days?\b", re.IGNORECASE), -1),  # -1 = from group
)


def parse_time_range(text: str) -> tuple[str, str] | None:
    """Parse a time expression in ``text`` into an (start, end) ISO date range.

    Returns None when no time expression is found. End is always today.
    Deterministic.
    """
    today = datetime.now(UTC).date()
    for pattern, days in _TIME_PATTERNS:
        match = pattern.search(text)
        if match:
            if days == -1:
                days = int(match.group(1))
            start = today - timedelta(days=days)
            return start.isoformat(), today.isoformat()
    return None


def _strip_time_words(text: str) -> str:
    """Remove recognized time expressions so they don't pollute keyword search."""
    cleaned = text
    for pattern, _ in _TIME_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ?.,!")


def _episodic_hits(
    data_dir: Path, keywords: str, date_range: tuple[str, str] | None, limit: int
) -> list[dict[str, Any]]:
    """Search episodes.db; returns [{text, date, source, score}]."""
    path = data_dir / _EPISODES_DB
    if not path.exists():
        return []
    store = SQLiteDocumentStore(path)
    hits: list[dict[str, Any]] = []
    for doc in store.search(keywords, limit=limit):
        if doc.get("type") != "event":
            continue
        doc_date = str(doc.get("date", ""))
        if date_range is not None and not (date_range[0] <= doc_date <= date_range[1]):
            continue
        text = str(doc.get("text", ""))
        score = sum(text.lower().count(t) for t in keywords.lower().split() if t)
        hits.append({"text": text, "date": doc_date, "source": "episodic", "score": score})
    return hits


async def _memory_hits(context: SkillContext, keywords: str, limit: int) -> list[dict[str, Any]]:
    """Search context.memory.recall; returns [{text, date, source, score}]."""
    hits: list[dict[str, Any]] = []
    try:
        results = await context.memory.recall(keywords, limit=limit)
    except Exception:
        return hits
    for rank, hit in enumerate(results):
        hits.append(
            {
                "text": str(getattr(hit, "text", "")),
                "date": str(getattr(hit, "date", "") or ""),
                "source": "memory",
                "score": float(limit - rank),
            }
        )
    return hits


def merge_rank(
    *hit_lists: list[dict[str, Any]], limit: int = 10
) -> list[dict[str, Any]]:
    """Merge hit lists and rank by (score, date) descending; dedupe by text."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for hits in hit_lists:
        for hit in hits:
            text = str(hit.get("text", ""))
            if text and text not in seen:
                seen.add(text)
                merged.append(hit)
    merged.sort(
        key=lambda hit: (float(hit.get("score", 0.0)), str(hit.get("date", ""))),
        reverse=True,
    )
    return merged[:limit]


class MemoryNlSearchSkill(Skill):
    """Searches memory with natural-language time expressions."""

    name = "memory_nl_search"
    description = "NL memory search with time-expression parsing across sources."
    intents = ("memory.search",)
    required_capabilities = ("skills.execute", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        """Parse time expressions, search episodes + memory, merge and rank."""
        data_dir = require_data_dir(context)
        query = context.message.strip()
        if not query:
            return "memory search: say what to search for"
        date_range = parse_time_range(query)
        keywords = _strip_time_words(query) or query
        episodic = _episodic_hits(data_dir, keywords, date_range, limit=10)
        mem = await _memory_hits(context, keywords, limit=10)
        results = merge_rank(episodic, mem, limit=10)
        if not results:
            return "memory search: no matches"
        lines = [
            f"- [{hit['source']}] {hit['date'] or '?'}: {str(hit['text'])[:140]}"
            for hit in results
        ]
        when = (
            f" ({date_range[0]}..{date_range[1]})" if date_range is not None else ""
        )
        return f"memory search{when}:\n" + "\n".join(lines)


SKILLS: list[Skill] = [MemoryNlSearchSkill()]
