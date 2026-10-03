"""Follow-up reminders: natural-language scheduling plus an hourly tick.

"follow up with <who> about <what> in <N> days" (English) or
"<N> din me <who> ko <what> ke liye yaad dilao" (Hinglish) stores a
reminder in ``data_dir/"followups.db"``. Every handle call — including
the hourly background tick — notifies for due items and marks them done.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime

from skills.base import Skill, SkillContext, require_data_dir

_EN_RE = re.compile(
    r"follow\s*up\s+with\s+(?P<who>.+?)\s+about\s+(?P<what>.+?)\s+in\s+"
    r"(?P<days>\d+)\s*days?",
    re.IGNORECASE,
)
_HI_RE = re.compile(
    r"(?P<days>\d+)\s*din\s+me(?:in)?\s+(?P<who>.+?)\s+ko\s+(?P<what>.+?)\s+"
    r"ke\s+liye\s+yaad\s+dilao",
    re.IGNORECASE,
)


def _notify(context: SkillContext, text: str) -> str:
    """Send a notification if a notification center is wired; else note it."""
    center = context.notifications
    if center is None:
        return " (notification center unavailable)"
    try:
        center.notify(text)
    except Exception as exc:  # noqa: BLE001 — report, don't crash the tick
        return f" (notify failed: {exc})"
    return " (notified)"


@dataclass
class Followup:
    """One scheduled reminder."""

    id: int
    who: str
    what: str
    due_ts: float


class FollowupStore:
    """SQLite follow-ups with due/notified tracking."""

    def __init__(self, path: object) -> None:
        self._path = str(path)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS followups ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "who TEXT NOT NULL, what TEXT NOT NULL, "
                "due_ts REAL NOT NULL, created_ts REAL NOT NULL, "
                "notified INTEGER NOT NULL DEFAULT 0)"
            )

    def add(self, who: str, what: str, due_ts: float) -> int:
        """Schedule a follow-up; returns its id."""
        with sqlite3.connect(self._path) as conn:
            cur = conn.execute(
                "INSERT INTO followups (who, what, due_ts, created_ts) VALUES (?, ?, ?, ?)",
                (who, what, due_ts, time.time()),
            )
            return int(cur.lastrowid or 0)

    def due(self, now: float) -> list[Followup]:
        """Unnotified follow-ups whose time has come."""
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT id, who, what, due_ts FROM followups "
                "WHERE notified = 0 AND due_ts <= ? ORDER BY due_ts ASC",
                (now,),
            ).fetchall()
        return [Followup(int(r[0]), str(r[1]), str(r[2]), float(r[3])) for r in rows]

    def pending(self) -> list[Followup]:
        """All unnotified follow-ups, soonest first."""
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT id, who, what, due_ts FROM followups "
                "WHERE notified = 0 ORDER BY due_ts ASC"
            ).fetchall()
        return [Followup(int(r[0]), str(r[1]), str(r[2]), float(r[3])) for r in rows]

    def mark_notified(self, item_id: int) -> None:
        """Record that a due reminder was delivered."""
        with sqlite3.connect(self._path) as conn:
            conn.execute("UPDATE followups SET notified = 1 WHERE id = ?", (item_id,))


class FollowupTrackerSkill(Skill):
    """Schedules follow-up reminders and notifies when they come due."""

    name = "followup_tracker"
    description = (
        "Tracks 'follow up with <who> about <what> in <N> days' (also "
        "Hinglish) and notifies when reminders come due on the hourly tick."
    )
    intents = ("followup.add", "followup.list")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 3600.0

    def _store(self, context: SkillContext) -> FollowupStore:
        return FollowupStore(require_data_dir(context) / "followups.db")

    async def handle(self, context: SkillContext) -> str:
        store = self._store(context)
        now = time.time()
        lines: list[str] = []

        for item in store.due(now):
            note = f"reminder: follow up with {item.who} about {item.what}"
            lines.append(note + _notify(context, note))
            store.mark_notified(item.id)

        text = context.message.strip()
        match = _EN_RE.search(text) or _HI_RE.search(text)
        if match:
            days = int(match.group("days"))
            who = match.group("who").strip()
            what = match.group("what").strip()
            if not who or not what:
                lines.append("could not parse who/what — try 'follow up with <who> about <what> in <N> days'")
            else:
                due_ts = now + days * 86400.0
                item_id = store.add(who, what, due_ts)
                day = datetime.fromtimestamp(due_ts).strftime("%Y-%m-%d")
                lines.append(f"follow-up #{item_id} set: {who} — {what} (due {day})")
        elif text.strip().lower() in ("list", "followups", "followup list", "show followups"):
            pending = store.pending()
            if not pending:
                lines.append("no pending follow-ups")
            else:
                lines.append("pending follow-ups:")
                for item in pending:
                    day = datetime.fromtimestamp(item.due_ts).strftime("%Y-%m-%d")
                    lines.append(f"#{item.id} {item.who} — {item.what} (due {day})")

        if not lines:
            return (
                "followup usage: 'follow up with <who> about <what> in <N> days' "
                "or '<N> din me <who> ko <what> ke liye yaad dilao'; 'list' shows pending"
            )
        return "\n".join(lines)


SKILLS: list[Skill] = [FollowupTrackerSkill()]
