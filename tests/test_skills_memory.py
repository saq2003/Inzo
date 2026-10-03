"""Memory skill tests (offline, deterministic; SQLite stores in tmp dirs)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from skills.base import Skill, SkillContext
from skills.discovery import build_skill_registry
from skills.memory.pref_learn import get_preference
from storage.sqlite_store import SQLiteKVStore


def _ctx(tmp_path: Path, message: str) -> SkillContext:
    """Bare skill context over an isolated data dir."""
    return SkillContext(
        actor="test", message=message, memory=None, tools=None, data_dir=tmp_path
    )


def _skill(name: str) -> Skill:
    """Fetch a skill from a fresh registry."""
    return build_skill_registry().get(name)


def test_episodic_record_then_recall(tmp_path: Path) -> None:
    """A recorded event is found again by keyword recall."""
    skill = _skill("episodic_memory")
    recorded = asyncio.run(
        skill.handle(_ctx(tmp_path, "record: fixed the leaky faucet #home"))
    )
    assert "recorded" in recorded

    recalled = asyncio.run(skill.handle(_ctx(tmp_path, "recall: faucet")))
    assert "faucet" in recalled


def test_episodic_recall_miss(tmp_path: Path) -> None:
    """Recall with no matching events says so honestly."""
    skill = _skill("episodic_memory")
    result = asyncio.run(skill.handle(_ctx(tmp_path, "recall: zzzqxj")))
    assert "no matching" in result


def test_people_add_then_lookup(tmp_path: Path) -> None:
    """An added person is returned by lookup."""
    skill = _skill("people_graph")
    added = asyncio.run(skill.handle(_ctx(tmp_path, "add person: Ada Lovelace")))
    assert "Ada Lovelace" in added

    found = asyncio.run(skill.handle(_ctx(tmp_path, "lookup: Ada Lovelace")))
    assert "Ada Lovelace" in found


def test_pref_learn_actually_prefer_tea(tmp_path: Path) -> None:
    """'actually prefer tea' is learned; get_preference returns 'tea'."""
    skill = _skill("pref_learn")
    result = asyncio.run(skill.handle(_ctx(tmp_path, "actually prefer tea")))
    assert "learned" in result

    store = SQLiteKVStore(tmp_path / "prefs.db")
    assert get_preference(store, "preference") == "tea"


def test_goals_habits_checkin_twice_streak(tmp_path: Path) -> None:
    """Two same-day checkins give a streak of at least one day."""
    skill = _skill("goals_habits")
    first = asyncio.run(skill.handle(_ctx(tmp_path, "checkin: run")))
    second = asyncio.run(skill.handle(_ctx(tmp_path, "checkin: run | morning run")))
    assert "streak 1d" in first
    assert "streak 1d" in second

    status = asyncio.run(skill.handle(_ctx(tmp_path, "status: run")))
    assert "streak 1d" in status


def test_memory_nl_search_roundtrip(tmp_path: Path) -> None:
    """Episodic records are visible to the NL memory search skill."""
    episodic = _skill("episodic_memory")
    asyncio.run(episodic.handle(_ctx(tmp_path, "record: bought fresh samosas #food")))

    search = _skill("memory_nl_search")
    result = asyncio.run(search.handle(_ctx(tmp_path, "samosas")))
    assert "samosas" in result
