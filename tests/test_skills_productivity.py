"""Productivity skill tests (offline, deterministic; SQLite stores in tmp dirs)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from skills.base import Skill, SkillContext
from skills.discovery import build_skill_registry
from storage.sqlite_store import SQLiteKVStore


def _ctx(tmp_path: Path, message: str) -> SkillContext:
    """Bare skill context over an isolated data dir."""
    return SkillContext(
        actor="test", message=message, memory=None, tools=None, data_dir=tmp_path
    )


def _skill(name: str) -> Skill:
    """Fetch a skill from a fresh registry."""
    return build_skill_registry().get(name)


class _NotifySink:
    """Single-arg notify sink that records delivered messages."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def notify(self, text: str) -> None:
        self.messages.append(text)


def test_reminders_add_in_1_minute_then_tick_fires(tmp_path: Path) -> None:
    """'add in 1 minute' stores a reminder; a tick fires it when due."""
    skill = _skill("reminders")
    added = asyncio.run(
        skill.handle(_ctx(tmp_path, "add in 1 minute take out trash"))
    )
    assert "reminder set for" in added

    # Seed an already-due reminder the same way the skill stores them.
    kv = SQLiteKVStore(tmp_path / "reminders.db")
    due = datetime.now().astimezone() - timedelta(seconds=30)
    kv.put(
        "reminder:past1",
        json.dumps({"text": "past reminder", "due_iso": due.isoformat()}),
    )
    kv.put("reminders:index", json.dumps(["past1"]))

    sink = _NotifySink()
    ctx = SkillContext(
        actor="test",
        message="tick:reminders",
        memory=None,
        tools=None,
        data_dir=tmp_path,
        notifications=sink,
    )
    fired = asyncio.run(skill.handle(ctx))
    assert "fired 1 due reminder" in fired
    assert any("past reminder" in message for message in sink.messages)


def test_calendar_add_overlap_warns(tmp_path: Path) -> None:
    """An overlapping event is added with an overlap warning."""
    skill = _skill("calendar_local")
    first = asyncio.run(
        skill.handle(
            _ctx(
                tmp_path,
                "add Standup | 2026-10-05T09:00 | 2026-10-05T09:30",
            )
        )
    )
    assert "event added" in first

    second = asyncio.run(
        skill.handle(
            _ctx(
                tmp_path,
                "add Clash | 2026-10-05T09:15 | 2026-10-05T09:45",
            )
        )
    )
    assert "overlaps" in second


def test_task_prioritizer_orders_by_importance(tmp_path: Path) -> None:
    """Higher-importance tasks rank above lower-importance ones."""
    skill = _skill("task_prioritizer")
    asyncio.run(skill.handle(_ctx(tmp_path, "add water plants importance 1")))
    asyncio.run(skill.handle(_ctx(tmp_path, "add file taxes importance 5")))

    ranked = asyncio.run(skill.handle(_ctx(tmp_path, "prioritize")))
    assert ranked.index("file taxes") < ranked.index("water plants")


def test_smart_notes_save_then_search(tmp_path: Path) -> None:
    """A saved note is found by search."""
    skill = _skill("smart_notes")
    saved = asyncio.run(
        skill.handle(_ctx(tmp_path, "save remember to buy ghee on thursday"))
    )
    assert "saved" in saved.lower() or "note" in saved.lower()

    found = asyncio.run(skill.handle(_ctx(tmp_path, "search ghee")))
    assert "ghee" in found
