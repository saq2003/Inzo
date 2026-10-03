"""Episodic memory skill: append-only event log with keyword/time recall.

Real (deterministic, stdlib): events are stored as documents in a SQLite
document store with an ISO date field for time filtering; :func:`record_event`
and :func:`recall_events` implement the log, and :meth:`EpisodicMemorySkill.handle`
speaks a small message protocol (``record: <text> #tag`` / ``recall: <keywords>``).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_DB_NAME = "episodes.db"
_TAG = re.compile(r"#(\w+)")


def _today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def record_event(
    store: SQLiteDocumentStore, actor: str, text: str, tags: list[str] | None = None
) -> str:
    """Record an event; returns the event id."""
    found = tags if tags is not None else _TAG.findall(text)
    return store.add(
        {
            "type": "event",
            "actor": actor,
            "text": text,
            "tags": found,
            "date": _today_iso(),
        }
    )


def recall_events(
    store: SQLiteDocumentStore,
    *,
    keywords: str = "",
    hours_back: float | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Recall events by keywords and/or recency; newest first.

    ``hours_back`` is day-granular: it filters on the event's ISO ``date``
    field (the document store does not expose per-document timestamps to
    search). Results are ordered newest-first by insertion order.
    """
    cutoff_date: str | None = None
    if hours_back is not None:
        cutoff_date = (datetime.now(UTC) - timedelta(hours=hours_back)).date().isoformat()
    docs = store.search(keywords, limit=1000)
    events: list[dict[str, Any]] = []
    for doc in docs:
        if doc.get("type") != "event":
            continue
        if keywords:
            haystack = (
                f"{doc.get('text', '')} {' '.join(str(t) for t in doc.get('tags', []))}"
            ).lower()
            if not all(term in haystack for term in keywords.lower().split()):
                continue
        event = cast("dict[str, Any]", dict(doc))
        if cutoff_date is not None and str(event.get("date", "")) < cutoff_date:
            continue
        events.append(event)
    # store.search() already returns newest first; preserve that order.
    return events[:limit]


class EpisodicMemorySkill(Skill):
    """Records and recalls episodic events."""

    name = "episodic_memory"
    description = "Append-only episodic event log with keyword and time recall."
    intents = ("episodic.record", "episodic.recall")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        """Speak the message protocol.

        ``record: <text> #tag`` stores an event; ``recall: <keywords>`` or
        ``recall last <N>h: <keywords>`` searches recent events.
        """
        data_dir = require_data_dir(context)
        store = SQLiteDocumentStore(data_dir / _DB_NAME)
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("record:"):
            body = text.split(":", 1)[1].strip()
            if not body:
                return "episodic: nothing to record"
            event_id = record_event(store, context.actor, body)
            return f"episodic: recorded event (id={event_id})"
        if lowered.startswith("recall"):
            rest = text.split(":", 1)[1].strip() if ":" in text else ""
            hours_back: float | None = None
            match = re.match(r"last\s+(\d+(?:\.\d+)?)h\s*(.*)", rest, re.IGNORECASE)
            if match:
                hours_back = float(match.group(1))
                rest = match.group(2)
            events = recall_events(store, keywords=rest, hours_back=hours_back)
            if not events:
                return "episodic: no matching events"
            lines = [
                f"- {event.get('date', '?')}: {str(event.get('text', ''))[:140]}"
                for event in events
            ]
            return "episodic events:\n" + "\n".join(lines)
        return "episodic: use 'record: <text> #tag' or 'recall: <keywords>'"


SKILLS: list[Skill] = [EpisodicMemorySkill()]
