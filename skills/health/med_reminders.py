"""Medication reminder skill (fully local, deterministic).

Meds ``{name, times: [HH:MM]}`` persist in ``data_dir/"health.db"``. On the
background tick (every 300 s) the skill checks whether now falls inside a
15-minute window after any scheduled dose time and notifies once per
medication per time per day (dedupe key includes the calendar date).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

MEDS_KEY = "meds:list"
NOTIFIED_PREFIX = "meds:notified:"
WINDOW_MINUTES = 15
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


@dataclass(frozen=True)
class Medication:
    """One medication with its daily dose times (HH:MM, 24 h)."""

    name: str
    times: tuple[str, ...]


def _check_time(value: str) -> str:
    """Validate 'HH:MM'; raise ValueError on bad input."""
    match = TIME_RE.match(value.strip())
    if not match or not 0 <= int(match.group(1)) <= 23 or not 0 <= int(match.group(2)) <= 59:
        raise ValueError(f"bad time {value!r}: expected HH:MM")
    return value.strip()


def _notify(context: SkillContext, text: str) -> str:
    center = context.notifications
    if center is None:
        return " (notification center unavailable)"
    try:
        center.notify(text)
    except Exception as exc:  # noqa: BLE001 — report, don't crash the tick
        return f" (notify failed: {exc})"
    return " (notified)"


class MedRemindersSkill(Skill):
    """Reminds of medication doses on a background tick."""

    name = "med_reminders"
    description = (
        "Keeps a list of medications with daily dose times and notifies "
        "when a dose is due (15-minute window, one reminder per day per dose)."
    )
    intents = ("med.add", "med.list")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 300.0

    def _store(self, context: SkillContext) -> SQLiteKVStore:
        return SQLiteKVStore(require_data_dir(context) / "health.db")

    def _meds(self, context: SkillContext) -> list[Medication]:
        raw = self._store(context).get(MEDS_KEY)
        if not raw:
            return []
        docs = cast("list[dict[str, Any]]", json.loads(raw))
        return [
            Medication(name=str(m["name"]), times=tuple(str(t) for t in m["times"])) for m in docs
        ]

    def _save_meds(self, context: SkillContext, meds: list[Medication]) -> None:
        self._store(context).put(
            MEDS_KEY,
            json.dumps([{"name": m.name, "times": list(m.times)} for m in meds]),
        )

    def _tick(self, context: SkillContext, now: datetime) -> str:
        store = self._store(context)
        today = now.date().isoformat()
        due: list[str] = []
        for med in self._meds(context):
            for dose_time in med.times:
                hour, minute = int(dose_time[:2]), int(dose_time[3:])
                scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                delta_min = (now - scheduled).total_seconds() / 60.0
                if 0 <= delta_min < WINDOW_MINUTES:
                    key = f"{NOTIFIED_PREFIX}{today}:{med.name}:{dose_time}"
                    if store.get(key):
                        continue  # already reminded today
                    store.put(key, "1")
                    due.append(f"{med.name} ({dose_time})")
        if not due:
            return "tick: no doses due"
        return "dose due: " + ", ".join(due) + _notify(context, "medication due: " + ", ".join(due))

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lower = text.lower()

        if lower == "tick":
            return self._tick(context, datetime.now(UTC).astimezone())

        if lower == "list":
            meds = self._meds(context)
            if not meds:
                return "no medications tracked — 'add <name> at HH:MM[,HH:MM]'"
            return "\n".join(f"{m.name}: {', '.join(m.times)}" for m in meds)

        if lower.startswith("add "):
            # "add <name> at HH:MM[, HH:MM ...]"
            rest = text[4:].strip()
            if " at " not in rest.lower():
                return "usage: add <name> at HH:MM[, HH:MM]"
            name_part, _, times_part = rest.partition(" at ")
            name = name_part.strip()
            if not name:
                return "usage: add <name> at HH:MM[, HH:MM]"
            try:
                times = tuple(_check_time(t) for t in times_part.split(",") if t.strip())
            except ValueError as exc:
                return str(exc)
            if not times:
                return "usage: add <name> at HH:MM[, HH:MM]"
            meds = [m for m in self._meds(context) if m.name != name]
            meds.append(Medication(name=name, times=times))
            self._save_meds(context, meds)
            return f"tracking {name}: {', '.join(times)}"

        if lower.startswith("remove "):
            name = text[7:].strip()
            meds = [m for m in self._meds(context) if m.name != name]
            self._save_meds(context, meds)
            return f"removed {name} (if present)"

        return "meds: 'add <name> at HH:MM[, HH:MM]', 'list', 'remove <name>'"


SKILLS: list[Skill] = [MedRemindersSkill()]
