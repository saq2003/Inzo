"""Security skill tests (offline, deterministic; no real secrets leave the box)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from skills.base import Skill, SkillContext
from skills.discovery import build_skill_registry
from skills.security.netguard import NetworkGuard
from skills.security.secret_vault import Vault, VaultError


def _ctx(tmp_path: Path, message: str) -> SkillContext:
    """Bare skill context over an isolated data dir."""
    return SkillContext(
        actor="test", message=message, memory=None, tools=None, data_dir=tmp_path
    )


def _skill(name: str) -> Skill:
    """Fetch a skill from a fresh registry."""
    return build_skill_registry().get(name)


def test_local_only_mode_on_blocks_network(tmp_path: Path) -> None:
    """Turning local-only mode on makes the guard block everything."""
    skill = _skill("local_only_mode")
    turned_on = asyncio.run(skill.handle(_ctx(tmp_path, "on")))
    assert "LOCAL_ONLY" in turned_on

    guard = NetworkGuard(tmp_path)
    assert guard.is_blocked("any_skill", "https://example.com") is True

    turned_off = asyncio.run(skill.handle(_ctx(tmp_path, "off")))
    assert "normal" in turned_off
    assert guard.is_blocked("any_skill", "https://example.com") is False


def test_voice_lock_pin_roundtrip(tmp_path: Path) -> None:
    """A set PIN fails on the wrong value and succeeds on the right one."""
    skill = _skill("voice_lock")
    pinned = asyncio.run(skill.handle(_ctx(tmp_path, "set pin 1234")))
    assert "PIN set" in pinned

    wrong = asyncio.run(skill.handle(_ctx(tmp_path, "unlock 0000")))
    assert wrong != "unlocked"

    right = asyncio.run(skill.handle(_ctx(tmp_path, "unlock 1234")))
    assert right == "unlocked"


def test_password_audit_common_password(tmp_path: Path) -> None:
    """'password123' scores low and is flagged as a common password."""
    result = asyncio.run(
        _skill("password_audit").handle(_ctx(tmp_path, "audit password123"))
    )
    assert "COMMON PASSWORD" in result
    assert "score" in result


def test_password_audit_strong_password(tmp_path: Path) -> None:
    """A long random password scores well with no common flag."""
    result = asyncio.run(
        _skill("password_audit").handle(
            _ctx(tmp_path, "audit Tr7$kQ!mZx9vLp2#wN8b")
        )
    )
    assert "COMMON PASSWORD" not in result
    assert "strong" in result


def test_secret_vault_store_and_retrieve(tmp_path: Path) -> None:
    """Stored secrets retrieve with the right password; wrong raises."""
    skill = _skill("secret_vault")
    stored = asyncio.run(
        skill.handle(_ctx(tmp_path, "store github token hunter2"))
    )
    assert "stored secret" in stored

    got = asyncio.run(skill.handle(_ctx(tmp_path, "get github hunter2")))
    assert "token" in got

    vault = Vault.for_context(_ctx(tmp_path, ""))
    with pytest.raises(VaultError):
        vault.retrieve("github", "wrong-password")
