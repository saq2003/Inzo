"""Autonomous background goal pursuit.

Real deterministic logic: natural-language goals are classified into a
kind (learn/fitness/finance/build/other) by keyword rules, decomposed
into 3-6 concrete steps from kind templates, and advanced on a
background tick. Goals persist as JSON in ``data_dir/"agoals.db"`` via
``SQLiteKVStore``.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE_FILE = "agoals.db"
_STORE_KEY = "agoals"
# Ticks (each tick = one background run) before a step is considered done.
_TICKS_PER_STEP = 2

# Step templates per goal kind. 3-6 concrete, ordered steps each.
_GOAL_TEMPLATES: dict[str, list[str]] = {
    "learn": [
        "Define the syllabus: list the exact topics or chapters to cover",
        "Gather materials: one book/course plus one practice source",
        "Study in 25-minute focused blocks, one topic per block",
        "Practice daily: exercises, flashcards, or a small project",
        "Self-test weekly and write down what is still unclear",
        "Teach or summarize the topic to lock in understanding",
    ],
    "fitness": [
        "Set a measurable baseline (time, distance, or max reps)",
        "Plan a weekly schedule: 3-4 sessions with rest days",
        "Start at 60% intensity and increase by ~10% per week",
        "Track every session: duration, distance, or weights",
        "Review progress after 4 weeks and adjust the plan",
    ],
    "finance": [
        "Write down the exact target amount and deadline",
        "Audit current spending for one week to find leaks",
        "Set a monthly budget with a fixed savings transfer",
        "Automate the transfer on payday so it happens first",
        "Review monthly and redirect windfalls to the goal",
    ],
    "build": [
        "Write a one-paragraph spec: what it does and for whom",
        "Break the spec into a task list ordered by dependency",
        "Build the smallest working version (MVP) first",
        "Test the MVP end to end and fix the top 3 issues",
        "Polish, document, and ship or demo it",
    ],
    "other": [
        "Write the goal as one measurable sentence",
        "List the first three concrete actions needed",
        "Do the smallest action today",
        "Schedule the next two actions with dates",
    ],
}

# Keyword rules mapping a goal text to its kind.
_KIND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "learn": (
        "learn",
        "study",
        "read",
        "course",
        "tutorial",
        "language",
        "book",
        "exam",
        "skill",
        "class",
    ),
    "fitness": (
        "gym",
        "run",
        "fitness",
        "weight",
        "workout",
        "yoga",
        "health",
        "exercise",
        "marathon",
        "diet",
        "swim",
    ),
    "finance": (
        "save",
        "invest",
        "money",
        "budget",
        "debt",
        "finance",
        "retire",
        "income",
        "loan",
        "savings",
    ),
    "build": (
        "build",
        "make",
        "create",
        "app",
        "website",
        "project",
        "code",
        "startup",
        "launch",
        "write",
        "design",
    ),
}

Goal = dict[str, Any]


def classify_goal_kind(text: str) -> str:
    """Classify a goal text into a kind by keyword rules (deterministic)."""
    lowered = text.lower()
    best_kind = "other"
    best_hits = 0
    for kind, keywords in _KIND_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best_hits = hits
            best_kind = kind
    return best_kind


def decompose_goal(text: str, kind: str) -> list[dict[str, Any]]:
    """Build the ordered step list for a goal from its kind template."""
    steps = _GOAL_TEMPLATES.get(kind, _GOAL_TEMPLATES["other"])
    step_dicts: list[dict[str, Any]] = [
        {"text": step, "status": "pending", "checkins": 0} for step in steps
    ]
    if step_dicts:
        step_dicts[0]["status"] = "active"
    return step_dicts


def _load_goals(data_dir: Path) -> list[Goal]:
    store = SQLiteKVStore(data_dir / _STORE_FILE)
    raw = store.get(_STORE_KEY)
    if not raw:
        return []
    goals = cast("list[Goal]", json.loads(raw))
    return goals


def _save_goals(data_dir: Path, goals: list[Goal]) -> None:
    store = SQLiteKVStore(data_dir / _STORE_FILE)
    store.put(_STORE_KEY, json.dumps(goals))


async def _notify(context: SkillContext, title: str, body: str) -> bool:
    """Best-effort notification via ``core.notifications.NotificationCenter``.

    The center's ``notify`` is async and never raises; here ``None`` (bare
    unit-test contexts) simply means "no notification sent".
    """
    notifier = context.notifications
    if notifier is None:
        return False
    notify = getattr(notifier, "notify", None)
    if not callable(notify):
        return False
    try:
        await notify(title, body)
    except Exception:
        return False
    return True


class AutonomousGoalsSkill(Skill):
    """Pursues user goals in the background: decompose, tick, report."""

    name = "autonomous_goals"
    description = (
        "Background goal pursuit: 'add <goal>' decomposes a goal into steps, "
        "the hourly tick advances steps, 'status' reports progress."
    )
    intents = ("agoal.add", "agoal.status")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 3600.0

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        message = context.message.strip()
        lowered = message.lower()
        if lowered == "tick" or lowered.startswith("tick "):
            return await self._tick(context, data_dir)
        if lowered.startswith("add ") or lowered.startswith("add:"):
            return await self._add(context, data_dir, message)
        if "status" in lowered:
            return self._status(data_dir)
        return "autonomous_goals: use 'add <goal text>' to start a goal, 'status' for progress."

    async def _add(self, context: SkillContext, data_dir: Path, message: str) -> str:
        text = message.split(None, 1)[1].strip() if len(message.split(None, 1)) > 1 else ""
        if not text:
            return "usage: add <goal text>"
        kind = classify_goal_kind(text)
        goal: Goal = {
            "id": secrets.token_hex(4),
            "text": text,
            "kind": kind,
            "created": datetime.now(UTC).isoformat(),
            "steps": decompose_goal(text, kind),
            "current": 0,
            "done": False,
        }
        goals = _load_goals(data_dir)
        goals.append(goal)
        _save_goals(data_dir, goals)
        try:
            await context.memory.remember(
                "user", f"autonomous goal started: {text}", durable=True, kind="goal"
            )
        except Exception as exc:
            _ = exc  # memory is optional in bare contexts; the goal is persisted above
        steps = goal["steps"]
        listing = "\n".join(f"  {i + 1}. {s['text']}" for i, s in enumerate(steps))
        return (
            f"goal added [{kind}] (id={goal['id']}): {text}\n"
            f"decomposed into {len(steps)} steps:\n{listing}"
        )

    def _status(self, data_dir: Path) -> str:
        goals = _load_goals(data_dir)
        if not goals:
            return "no autonomous goals yet — use 'add <goal text>'."
        lines = [f"autonomous goals ({len(goals)}):"]
        for i, goal in enumerate(goals, 1):
            steps = cast("list[dict[str, Any]]", goal["steps"])
            done = sum(1 for s in steps if s["status"] == "done")
            pct = int(100 * done / len(steps)) if steps else 100
            if goal["done"]:
                lines.append(f"{i}. [{pct}%] {goal['text']} — complete")
            else:
                cur = steps[int(goal["current"])] if steps else {"text": "?"}
                lines.append(
                    f"{i}. [{pct}%] {goal['text']} — current step "
                    f"({int(goal['current']) + 1}/{len(steps)}): {cur['text']}"
                )
        return "\n".join(lines)

    async def _tick(self, context: SkillContext, data_dir: Path) -> str:
        goals = _load_goals(data_dir)
        events: list[str] = []
        for goal in goals:
            if goal["done"]:
                continue
            steps = cast("list[dict[str, Any]]", goal["steps"])
            idx = int(goal["current"])
            if idx >= len(steps):
                goal["done"] = True
                continue
            step = steps[idx]
            step["checkins"] = int(step["checkins"]) + 1
            events.append(f"check-in on '{step['text']}' ({step['checkins']}/{_TICKS_PER_STEP})")
            if int(step["checkins"]) >= _TICKS_PER_STEP:
                step["status"] = "done"
                goal["current"] = idx + 1
                if int(goal["current"]) >= len(steps):
                    goal["done"] = True
                    title = "goal completed"
                    body = str(goal["text"])
                else:
                    nxt = steps[int(goal["current"])]
                    nxt["status"] = "active"
                    title = f"goal progress: {goal['text']}"
                    body = f"step done — '{step['text']}'; next: '{nxt['text']}'"
                await _notify(context, title, body)
                events.append(f"{title}: {body}")
        _save_goals(data_dir, goals)
        if not events:
            return "tick: no active goals."
        return "tick:\n" + "\n".join(f"- {e}" for e in events)


SKILLS: list[Skill] = [AutonomousGoalsSkill()]
