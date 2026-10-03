"""Tool safety tests (Rule 11, Rule 12, Rule 13).

Rule 12: INZO must never execute arbitrary shell commands from
natural-language input. These tests pin that guarantee behaviorally.
"""

from __future__ import annotations

import asyncio

import pytest

from security.permissions import PermissionDenied
from tools.registry import UnknownToolError


def test_no_shell_like_tool_exists(tool_registry):
    names = tool_registry.names()
    for banned in ("shell", "exec", "command", "subprocess", "bash", "terminal"):
        assert not any(banned in name for name in names), f"banned tool pattern: {banned}"


def test_unknown_tool_raises(tool_registry):
    with pytest.raises(UnknownToolError):
        asyncio.run(tool_registry.execute("shell", actor="user", args={}))


def test_calculator_rejects_code_injection(tool_registry):
    result = asyncio.run(
        tool_registry.execute(
            "calculator", actor="user", args={"expression": "__import__('os').system('x')"}
        )
    )
    assert result.ok is False


def test_calculator_computes(tool_registry):
    result = asyncio.run(
        tool_registry.execute("calculator", actor="user", args={"expression": "(2+3)*4"})
    )
    assert result.ok is True
    assert "20" in result.output


def test_unpermissioned_actor_denied(tool_registry):
    with pytest.raises(PermissionDenied):
        asyncio.run(
            tool_registry.execute("calculator", actor="intruder", args={"expression": "1+1"})
        )


def test_read_file_sandbox_escape_denied(tool_registry, tmp_path):
    (tmp_path / "ok.txt").write_text("hello")
    result = asyncio.run(
        tool_registry.execute(
            "read_file", actor="user", args={"path": "../outside.txt"}
        )
    )
    assert result.ok is False
    assert "escapes" in (result.error or "")


def test_missing_args_rejected(tool_registry):
    with pytest.raises(ValueError):
        asyncio.run(tool_registry.execute("calculator", actor="user", args={}))
