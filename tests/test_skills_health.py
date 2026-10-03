"""Health skill tests (offline, deterministic; SQLite stores in tmp dirs)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from skills.base import Skill, SkillContext
from skills.discovery import build_skill_registry


def _ctx(tmp_path: Path, message: str) -> SkillContext:
    """Bare skill context over an isolated data dir."""
    return SkillContext(
        actor="test", message=message, memory=None, tools=None, data_dir=tmp_path
    )


def _skill(name: str) -> Skill:
    """Fetch a skill from a fresh registry."""
    return build_skill_registry().get(name)


_SLEEP_CSV = """start_iso,end_iso,quality
2026-09-28T22:30:00,2026-09-29T06:30:00,80
2026-09-29T23:00:00,2026-09-30T06:45:00,70
2026-09-30T22:15:00,2026-10-01T06:00:00,85
"""


def test_sleep_analysis_sample_csv(tmp_path: Path) -> None:
    """Sleep analysis on a sample CSV reports an average duration."""
    result = asyncio.run(_skill("sleep_analysis").handle(_ctx(tmp_path, _SLEEP_CSV)))
    assert "nights analyzed: 3" in result
    assert "avg duration:" in result
    assert "h" in result


def test_workout_planner_days_present(tmp_path: Path) -> None:
    """A workout plan lists the requested training days."""
    result = asyncio.run(
        _skill("workout_planner").handle(_ctx(tmp_path, "strength beginner days 3"))
    )
    assert "3 days/week" in result
    assert "day 1" in result
    assert "day 3" in result


def test_mood_log_twice_then_trend(tmp_path: Path) -> None:
    """Two mood logs produce a trend with an average."""
    skill = _skill("mood_tracker")
    first = asyncio.run(skill.handle(_ctx(tmp_path, "log 4 decent day")))
    assert "logged" in first.lower()
    second = asyncio.run(skill.handle(_ctx(tmp_path, "log 3 okay-ish")))
    assert "logged" in second.lower()

    trend = asyncio.run(skill.handle(_ctx(tmp_path, "trend")))
    assert "average" in trend.lower() or "avg" in trend.lower() or "3.5" in trend


def test_diet_log_totals(tmp_path: Path) -> None:
    """Logged foods appear in the daily totals report."""
    skill = _skill("diet_log")
    asyncio.run(skill.handle(_ctx(tmp_path, "log roti sabzi 300")))
    asyncio.run(skill.handle(_ctx(tmp_path, "log chai 80")))

    report = asyncio.run(skill.handle(_ctx(tmp_path, "today")))
    assert "2 meal(s)" in report
    assert "380" in report


def test_med_reminders_add_and_list(tmp_path: Path) -> None:
    """A medication reminder can be added and listed."""
    skill = _skill("med_reminders")
    added = asyncio.run(skill.handle(_ctx(tmp_path, "add vitamin-d at 08:00")))
    assert "vitamin-d" in added

    listed = asyncio.run(skill.handle(_ctx(tmp_path, "list")))
    assert "vitamin-d" in listed
