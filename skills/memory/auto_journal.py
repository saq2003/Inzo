"""Auto-journal skill: builds a daily digest from events and habit check-ins.

Real (deterministic, stdlib): on ``journal.today`` (or the daily tick) the
skill reads today's documents from the episodic ``episodes.db`` store and,
when present, today's check-ins from the ``habits.db`` store, renders a
digest, and stores it in ``journal.db``. Missing source stores are tolerated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_DB_NAME = "journal.db"
_EPISODES_DB = "episodes.db"
_HABITS_DB = "habits.db"


def _today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def _today_texts(store: SQLiteDocumentStore, doc_type: str) -> list[str]:
    """Return today's texts of ``doc_type``; empty when none match."""
    today = _today_iso()
    texts: list[str] = []
    for doc in store.search(today, limit=1000):
        if doc.get("type") != doc_type:
            continue
        if doc_type == "event":
            texts.append(str(doc.get("text", "")))
        elif doc_type == "checkin":
            habit = str(doc.get("habit", "?"))
            note = str(doc.get("note", "")).strip()
            texts.append(f"{habit}: {note}" if note else habit)
    return [text for text in texts if text]


def build_digest(
    events: list[str], checkins: list[str], *, date: str | None = None
) -> str:
    """Render a daily digest from today's events and habit check-ins."""
    lines = [f"# journal — {date or _today_iso()}", "", "## events"]
    if events:
        lines.extend(f"- {event}" for event in events)
    else:
        lines.append("- (none recorded)")
    lines.append("")
    lines.append("## habit check-ins")
    if checkins:
        lines.extend(f"- {checkin}" for checkin in checkins)
    else:
        lines.append("- (none recorded)")
    return "\n".join(lines)


def build_today_entry(data_dir: Path) -> str:
    """Build today's digest from episodes.db + habits.db (tolerating absence)."""
    events: list[str] = []
    checkins: list[str] = []
    episodes_path = data_dir / _EPISODES_DB
    if episodes_path.exists():
        events = _today_texts(SQLiteDocumentStore(episodes_path), "event")
    habits_path = data_dir / _HABITS_DB
    if habits_path.exists():
        checkins = _today_texts(SQLiteDocumentStore(habits_path), "checkin")
    digest = build_digest(events, checkins)
    store = SQLiteDocumentStore(data_dir / _DB_NAME)
    already = any(
        doc.get("type") == "journal_entry" and doc.get("date") == _today_iso()
        for doc in store.search(_today_iso(), limit=1000)
    )
    if not already:
        store.add({"type": "journal_entry", "date": _today_iso(), "text": digest})
    return digest


class AutoJournalSkill(Skill):
    """Builds and stores a daily journal digest."""

    name = "auto_journal"
    description = "Builds a daily journal digest from events and habit check-ins."
    intents = ("journal.today",)
    required_capabilities = (
        "skills.execute",
        "memory.read",
        "memory.write",
        "notify.send",
    )
    background = True
    local_only = True
    tick_interval_s = 86400.0

    async def handle(self, context: SkillContext) -> str:
        """Return (or build) today's journal entry."""
        data_dir = require_data_dir(context)
        return build_today_entry(data_dir)


SKILLS: list[Skill] = [AutoJournalSkill()]
