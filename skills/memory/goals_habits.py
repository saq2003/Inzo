"""Goals & habits skill: weekly goals, check-ins, and streak computation.

Real (deterministic, stdlib): goals ``{name, target_per_week}`` and
timestamped check-ins live in a SQLite document store; :func:`streak_days`
counts consecutive days (ending today or yesterday) with at least one
check-in for a habit.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from skills.base import Skill, SkillContext, SkillError, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_DB_NAME = "habits.db"


def _today() -> date:
    return datetime.now(UTC).date()


def add_goal(store: SQLiteDocumentStore, name: str, target_per_week: int) -> str:
    """Add a goal with a weekly target; returns the document id.

    Raises:
        SkillError: if the target is not positive.
    """
    if target_per_week <= 0:
        raise SkillError(f"target_per_week must be positive: {target_per_week}")
    return store.add(
        {"type": "goal", "name": name, "target_per_week": target_per_week}
    )


def checkin(store: SQLiteDocumentStore, habit: str, note: str = "") -> str:
    """Record a check-in for ``habit`` with today's date; returns the id."""
    return store.add(
        {
            "type": "checkin",
            "habit": habit,
            "note": note,
            "date": _today().isoformat(),
        }
    )


def _checkin_dates(store: SQLiteDocumentStore, habit: str) -> set[str]:
    """Return the set of ISO dates with at least one check-in for ``habit``."""
    dates: set[str] = set()
    for doc in store.search(f"checkin {habit}", limit=1000):
        if doc.get("type") == "checkin" and str(doc.get("habit", "")).lower() == habit.lower():
            dates.add(str(doc.get("date", "")))
    return dates


def streak_days(store: SQLiteDocumentStore, habit: str) -> int:
    """Count consecutive check-in days ending today (or yesterday).

    A streak broken today still counts if yesterday had a check-in, so a
    user who hasn't checked in yet today keeps their streak.
    """
    dates = _checkin_dates(store, habit)
    today = _today()
    cursor = today if today.isoformat() in dates else today - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def weekly_count(store: SQLiteDocumentStore, habit: str) -> int:
    """Count check-ins for ``habit`` in the last 7 days (inclusive)."""
    dates = _checkin_dates(store, habit)
    cutoff = _today() - timedelta(days=6)
    return sum(1 for d in dates if d >= cutoff.isoformat())


def status(store: SQLiteDocumentStore, habit: str) -> dict[str, Any]:
    """Return streak, this-week count, and goal target for ``habit``."""
    goals = [
        doc
        for doc in store.search(f"goal {habit}", limit=1000)
        if doc.get("type") == "goal" and str(doc.get("name", "")).lower() == habit.lower()
    ]
    target = int(goals[0].get("target_per_week", 0)) if goals else 0
    return {
        "habit": habit,
        "streak_days": streak_days(store, habit),
        "this_week": weekly_count(store, habit),
        "target_per_week": target,
    }


class GoalsHabitsSkill(Skill):
    """Tracks goals, habit check-ins, and streaks."""

    name = "goals_habits"
    description = "Weekly goals with check-ins and streak computation."
    intents = ("habit.checkin", "habit.status", "goal.add")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        """Speak the message protocol.

        ``goal add: <name> | <target_per_week>``, ``checkin: <habit>``,
        ``checkin: <habit> | <note>``, ``status: <habit>``.
        """
        data_dir = require_data_dir(context)
        store = SQLiteDocumentStore(data_dir / _DB_NAME)
        text = context.message.strip()
        lowered = text.lower()
        try:
            if lowered.startswith("goal add:"):
                parts = [p.strip() for p in text.split(":", 1)[1].split("|")]
                if len(parts) != 2 or not parts[0]:
                    return "goals: usage is 'goal add: <name> | <target_per_week>'"
                try:
                    target = int(parts[1])
                except ValueError as exc:
                    raise SkillError(f"target must be an integer: {parts[1]}") from exc
                goal_id = add_goal(store, parts[0], target)
                return f"goals: added '{parts[0]}' ({target}/week, id={goal_id})"
            if lowered.startswith("checkin:"):
                parts = [p.strip() for p in text.split(":", 1)[1].split("|")]
                if not parts[0]:
                    return "goals: usage is 'checkin: <habit> [| <note>]'"
                note = parts[1] if len(parts) > 1 else ""
                checkin_id = checkin(store, parts[0], note)
                streak = streak_days(store, parts[0])
                return (
                    f"goals: checked in '{parts[0]}' (id={checkin_id}, "
                    f"streak {streak}d)"
                )
            if lowered.startswith("status:"):
                habit = text.split(":", 1)[1].strip()
                if not habit:
                    return "goals: usage is 'status: <habit>'"
                info = status(store, habit)
                target = info["target_per_week"]
                target_str = f"/{target}" if target else ""
                return (
                    f"goals: '{habit}' — streak {info['streak_days']}d, "
                    f"this week {info['this_week']}{target_str}"
                )
        except SkillError as exc:
            return f"goals error: {exc}"
        return (
            "goals: use 'goal add: <name> | <target_per_week>', "
            "'checkin: <habit> [| <note>]', or 'status: <habit>'"
        )


SKILLS: list[Skill] = [GoalsHabitsSkill()]
