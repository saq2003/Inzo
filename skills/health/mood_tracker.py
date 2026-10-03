"""Mood tracker skill (fully local, deterministic).

Logs mood entries (1–5 plus an optional note) to ``data_dir/"health.db"``
and computes weekly trends: average, minimum, and the streak of
consecutive days with mood >= 4.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore


class MoodTrackerSkill(Skill):
    """Logs daily mood and reports weekly trends."""

    name = "mood_tracker"
    description = (
        "Logs mood (1-5) with an optional note and computes weekly trends: "
        "average, minimum, and the streak of days at mood 4 or better."
    )
    intents = ("mood.log", "mood.trend")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    def _store(self, context: SkillContext) -> SQLiteDocumentStore:
        return SQLiteDocumentStore(require_data_dir(context) / "health.db")

    def _log_entry(self, context: SkillContext, mood: int, note: str) -> None:
        doc: dict[str, Any] = {
            "kind": "mood_entry",
            "mood": mood,
            "note": note,
            "ts": datetime.now(UTC).isoformat(),
        }
        self._store(context).add(doc)

    def _entries(self, context: SkillContext, since: datetime) -> list[Mapping[str, Any]]:
        docs = self._store(context).search("mood_entry", limit=1000)
        entries = [d for d in docs if d.get("kind") == "mood_entry"]
        recent = [d for d in entries if datetime.fromisoformat(str(d["ts"])) >= since]
        return sorted(recent, key=lambda d: str(d["ts"]))

    def _trend(self, context: SkillContext) -> str:
        since = datetime.now(UTC) - timedelta(days=7)
        entries = self._entries(context, since)
        if not entries:
            return "no mood entries in the last 7 days — 'log <1-5> [note]'"
        moods = [int(e["mood"]) for e in entries]
        avg = sum(moods) / len(moods)
        by_day: dict[str, int] = {}
        for e in entries:
            day = datetime.fromisoformat(str(e["ts"])).date().isoformat()
            by_day[day] = max(by_day.get(day, 0), int(e["mood"]))
        streak = 0
        today = datetime.now(UTC).date()
        for offset in range(0, 14):
            day = (today - timedelta(days=offset)).isoformat()
            if by_day.get(day, 0) >= 4:
                streak += 1
            elif day in by_day:
                break
        return (
            f"7-day mood trend ({len(entries)} entries):\n"
            f"average: {avg:.1f}/5\n"
            f"minimum: {min(moods)}/5\n"
            f"streak of days >= 4: {streak}"
        )

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()

        if text.lower() in ("trend", "week"):
            return self._trend(context)

        if text.lower().startswith("log"):
            rest = text[3:].strip()
            parts = rest.split(maxsplit=1)
            if not parts:
                return "usage: log <1-5> [note]"
            try:
                mood = int(parts[0])
            except ValueError as exc:
                raise ValueError("mood must be an integer 1-5") from exc
            if not 1 <= mood <= 5:
                raise ValueError("mood must be 1-5")
            note = parts[1] if len(parts) > 1 else ""
            self._log_entry(context, mood, note)
            suffix = f" — noted: {note}" if note else ""
            return f"mood logged: {mood}/5{suffix}"

        return "mood: 'log <1-5> [note]', 'trend'"


SKILLS: list[Skill] = [MoodTrackerSkill()]
