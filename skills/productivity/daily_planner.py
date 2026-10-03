"""Daily planner: composes a morning plan from calendar, tasks, and habits."""

from __future__ import annotations

import inspect
import json
import sqlite3
from datetime import datetime
from typing import cast

from skills.base import Skill, SkillContext, require_data_dir
from skills.productivity.calendar_local import _format_event, _load_events
from skills.productivity.task_prioritizer import _load_tasks, score_task
from storage.sqlite_store import SQLiteKVStore


async def _notify(context: SkillContext, text: str) -> bool:
    """Deliver a notification when a notification center is wired."""
    center = context.notifications
    if center is None:
        return False
    send = getattr(center, "send", None) or getattr(center, "notify", None)
    if send is None:
        return False
    result = send(text)
    if inspect.isawaitable(result):
        await result
    return True


def _due_habits(context: SkillContext) -> list[str]:
    """Best-effort read of habit titles from habits.db; empty when absent."""
    path = require_data_dir(context) / "habits.db"
    if not path.exists():
        return []
    try:
        kv = SQLiteKVStore(path)
        raw_index = kv.get("habits:index")
        ids: list[str] = cast(list[str], json.loads(raw_index)) if raw_index else []
        titles: list[str] = []
        for habit_id in ids[:5]:
            raw = kv.get(f"habit:{habit_id}")
            if raw is None:
                continue
            data = cast(dict[str, object], json.loads(raw))
            title = data.get("title")
            if isinstance(title, str) and title:
                titles.append(title)
        return titles
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return []


class DailyPlannerSkill(Skill):
    """Composes the day's plan: events, top tasks, and habits."""

    name = "daily_planner"
    description = (
        "Morning briefing: 'today' builds the plan from today's calendar "
        "events, the top 3 tasks by priority score, and habits when present. "
        "The daily tick sends it as a notification."
    )
    intents = ("plan.today",)
    required_capabilities = ("skills.execute", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 86400.0

    async def handle(self, context: SkillContext) -> str:
        plan = self._build_plan(context)
        if not context.message.strip():
            await _notify(context, plan)
        return plan

    def _build_plan(self, context: SkillContext) -> str:
        now = datetime.now().astimezone()
        today = now.strftime("%Y-%m-%d")
        lines = [f"plan for {today}:"]

        events = [e for e in _load_events(context) if e.start.strftime("%Y-%m-%d") == today]
        lines.append("  events:")
        if events:
            lines.extend(f"    {_format_event(e)}" for e in events)
        else:
            lines.append("    none")

        tasks = _load_tasks(context)
        lines.append("  top tasks:")
        if tasks:
            ranked = sorted(tasks, key=lambda t: score_task(t, now), reverse=True)[:3]
            for task in ranked:
                due_str = task.due.strftime("%Y-%m-%d %H:%M") if task.due else "no due"
                lines.append(f"    {task.title} (due {due_str})")
        else:
            lines.append("    none")

        habits = _due_habits(context)
        lines.append("  habits:")
        if habits:
            lines.extend(f"    {title}" for title in habits)
        else:
            lines.append("    none tracked")
        return "\n".join(lines)


SKILLS: list[Skill] = [DailyPlannerSkill()]
