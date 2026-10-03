"""Home skill tests (offline, deterministic; no hardware is ever touched)."""

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


def test_temp_monitor_set_high_then_status(tmp_path: Path) -> None:
    """Setting the high threshold is reflected in status."""
    skill = _skill("temp_monitor")
    set_result = asyncio.run(skill.handle(_ctx(tmp_path, "set high 30")))
    assert "30.0" in set_result

    status = asyncio.run(skill.handle(_ctx(tmp_path, "status")))
    assert "30.0" in status
    assert "NOT configured" in status  # honest: no sensor adapter


def test_appliance_schedule_add_and_kwh_math(tmp_path: Path) -> None:
    """Scheduling a 2000 W appliance for 1.5 h yields 3.000 kWh/day."""
    skill = _skill("appliance_schedule")
    added = asyncio.run(
        skill.handle(_ctx(tmp_path, "schedule geyser on 05:00 off 06:30 watts 2000"))
    )
    assert "3.000 kWh/day" in added

    energy = asyncio.run(skill.handle(_ctx(tmp_path, "energy")))
    assert "2000 W" in energy
    assert "3.000 kWh/day" in energy


def test_lights_control_invalid_brightness_rejected(tmp_path: Path) -> None:
    """Brightness outside 0-100 is rejected with an error message."""
    skill = _skill("lights_control")
    asyncio.run(skill.handle(_ctx(tmp_path, "add light lamp1 Hall Lamp")))
    result = asyncio.run(skill.handle(_ctx(tmp_path, "set lamp1 on brightness 150")))
    assert "out of range" in result


def test_lights_control_valid_set_needs_hub(tmp_path: Path) -> None:
    """A valid set passes validation and honestly reports no hub adapter."""
    skill = _skill("lights_control")
    asyncio.run(skill.handle(_ctx(tmp_path, "add light lamp1 Hall Lamp")))
    result = asyncio.run(skill.handle(_ctx(tmp_path, "set lamp1 on brightness 80")))
    assert "not configured" in result.lower()


def test_camera_qa_without_adapter_honest(tmp_path: Path) -> None:
    """A camera question with no adapter says it is not configured."""
    result = asyncio.run(
        _skill("camera_qa").handle(_ctx(tmp_path, "ask who is at the door"))
    )
    assert "configur" in result.lower()
