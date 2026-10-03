"""Daemon-layer tests: event bus, notifications, skill engine, discovery, API.

All offline and deterministic. Async skill/bus calls are driven with
``asyncio.run`` inside plain sync tests (no pytest-asyncio in this repo).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.notifications import NotificationCenter
from security.permissions import PermissionDenied, PermissionManager
from skills.base import SkillError
from skills.discovery import build_skill_registry
from skills.engine import SkillEngine
from skills.registry import UnknownSkillError


def _make_engine(tmp_path: Path, permissions: PermissionManager) -> SkillEngine:
    """Build a SkillEngine with a fresh registry over ``tmp_path``."""
    return SkillEngine(
        registry=build_skill_registry(),
        permissions=permissions,
        memory=None,
        tools=None,
        data_dir=tmp_path,
    )


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


def test_event_bus_two_subscribers_both_fire() -> None:
    """Two subscribers on one topic both receive the payload."""
    bus = EventBus()
    received: list[tuple[str, dict[str, Any]]] = []

    async def first(payload: dict[str, Any]) -> None:
        received.append(("first", payload))

    async def second(payload: dict[str, Any]) -> None:
        received.append(("second", payload))

    bus.subscribe("topic.a", first)
    bus.subscribe("topic.a", second)
    asyncio.run(bus.publish("topic.a", {"n": 1}))

    assert bus.subscribers("topic.a") == 2
    assert ("first", {"n": 1}) in received
    assert ("second", {"n": 1}) in received


def test_event_bus_exception_in_one_does_not_break_other() -> None:
    """A failing handler is isolated; the other subscriber still fires."""

    async def broken(_payload: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    seen: list[dict[str, Any]] = []

    async def healthy(payload: dict[str, Any]) -> None:
        seen.append(payload)

    bus = EventBus()
    bus.subscribe("topic.b", broken)
    bus.subscribe("topic.b", healthy)
    asyncio.run(bus.publish("topic.b", {"ok": True}))

    assert seen == [{"ok": True}]


def test_event_bus_publish_no_subscribers_is_safe() -> None:
    """Publishing to an empty topic is a no-op, not an error."""
    bus = EventBus()
    asyncio.run(bus.publish("topic.empty", {"x": 1}))


# ---------------------------------------------------------------------------
# NotificationCenter
# ---------------------------------------------------------------------------


def test_notification_center_notify_inbox_mark_read_roundtrip(tmp_path: Path) -> None:
    """notify -> inbox_list -> mark_read marks the entry read."""
    center = NotificationCenter(tmp_path / "notifications")

    result = asyncio.run(center.notify("Hello", "world"))

    inbox = center.inbox_list()
    assert len(inbox) == 1
    assert inbox[0]["id"] == result["id"]
    assert inbox[0]["title"] == "Hello"
    assert inbox[0]["read"] is False

    assert center.mark_read(result["id"]) is True
    inbox = center.inbox_list()
    assert inbox[0]["read"] is True
    assert center.inbox_list(unread_only=True) == []


def test_notification_center_mark_read_unknown_id_false(tmp_path: Path) -> None:
    """mark_read returns False for an id that was never persisted."""
    center = NotificationCenter(tmp_path / "notifications")
    assert center.mark_read("no-such-id") is False


# ---------------------------------------------------------------------------
# SkillEngine
# ---------------------------------------------------------------------------


def test_skill_engine_unknown_skill_raises(tmp_path: Path) -> None:
    """Running an unregistered skill raises UnknownSkillError."""
    engine = _make_engine(tmp_path, PermissionManager())
    with pytest.raises(UnknownSkillError):
        asyncio.run(engine.run_skill("test", "no_such_skill"))


def test_skill_engine_disabled_skill_raises(tmp_path: Path) -> None:
    """A disabled skill raises SkillError even when the actor is allowed."""
    permissions = PermissionManager()
    permissions.grant("test", "skills.execute")
    engine = _make_engine(tmp_path, permissions)
    engine.registry.disable("time")
    with pytest.raises(SkillError):
        asyncio.run(engine.run_skill("test", "time"))


def test_skill_engine_revoked_capability_raises(tmp_path: Path) -> None:
    """A revoked capability raises PermissionDenied."""
    permissions = PermissionManager()
    permissions.grant("test", "skills.execute")
    assert permissions.revoke("test", "skills.execute") is True
    engine = _make_engine(tmp_path, permissions)
    with pytest.raises(PermissionDenied):
        asyncio.run(engine.run_skill("test", "time"))


def test_skill_engine_successful_run_returns_str(tmp_path: Path) -> None:
    """A granted skill run returns its string result."""
    permissions = PermissionManager()
    permissions.grant("test", "skills.execute")
    engine = _make_engine(tmp_path, permissions)
    result = asyncio.run(engine.run_skill("test", "time"))
    assert isinstance(result, str)
    assert "current time" in result


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discovery_finds_at_least_80_unique_named_skills() -> None:
    """Registry holds >= 80 skills with unique names."""
    registry = build_skill_registry()
    skills = registry.all_skills()
    assert len(skills) >= 80
    assert len({skill.name for skill in skills}) == len(skills)


def test_discovery_every_skill_background_with_description() -> None:
    """Background-first: every skill is headless-capable and documented."""
    registry = build_skill_registry()
    for skill in registry.all_skills():
        assert skill.background is True, f"{skill.name} is not background-first"
        assert skill.description.strip(), f"{skill.name} has an empty description"


# ---------------------------------------------------------------------------
# API (client fixture from conftest)
# ---------------------------------------------------------------------------


def test_api_daemon_status(client: TestClient) -> None:
    """GET /daemon/status returns 200 with skill counts."""
    response = client.get("/daemon/status")
    assert response.status_code == 200
    body = response.json()
    assert body["skills"] >= 80
    assert body["enabled_skills"] >= 80


def test_api_notifications_inbox(client: TestClient) -> None:
    """GET /notifications/inbox returns a JSON list."""
    response = client.get("/notifications/inbox")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_skills_run_time(client: TestClient) -> None:
    """POST /skills/run for the time skill returns the current time."""
    response = client.post("/skills/run", json={"skill": "time"})
    assert response.status_code == 200
    body = response.json()
    assert body["skill"] == "time"
    assert "current time" in body["result"]


def test_api_skills_run_unknown_404(client: TestClient) -> None:
    """POST /skills/run for an unknown skill returns 404."""
    response = client.post("/skills/run", json={"skill": "no_such_skill"})
    assert response.status_code == 404
