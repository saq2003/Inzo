"""Coding skill tests (offline, deterministic)."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from skills.base import Skill, SkillContext
from skills.coding.sql_builder import parse_spec
from skills.discovery import build_skill_registry


def _ctx(tmp_path: Path, message: str) -> SkillContext:
    """Bare skill context over an isolated data dir."""
    return SkillContext(
        actor="test", message=message, memory=None, tools=None, data_dir=tmp_path
    )


def _skill(name: str) -> Skill:
    """Fetch a skill from a fresh registry."""
    return build_skill_registry().get(name)


def test_mql5_build_contains_ontick(tmp_path: Path) -> None:
    """The MQL5 builder emits an EA with an OnTick handler."""
    result = asyncio.run(
        _skill("mql5_builder").handle(_ctx(tmp_path, "symbol=EURUSD fast_ma=10"))
    )
    assert "OnTick" in result
    assert "EURUSD" in result


def test_sql_builder_injection_raises() -> None:
    """Injection-shaped identifiers raise ValueError (never string-built)."""
    with pytest.raises(ValueError):
        parse_spec("table=users; DROP TABLE users--")
    with pytest.raises(ValueError):
        parse_spec("table=users where=x' OR '1'='1")


def test_sql_builder_valid_spec(tmp_path: Path) -> None:
    """A clean spec builds a parameterized query through handle()."""
    result = asyncio.run(
        _skill("sql_builder").handle(_ctx(tmp_path, "table=users cols=id,name"))
    )
    assert "parameterized query built" in result
    assert "users" in result


def test_codegen_debug_generates_parseable_function(tmp_path: Path) -> None:
    """'function' generation emits source that ast can parse."""
    result = asyncio.run(
        _skill("codegen_debug").handle(_ctx(tmp_path, "function add a, b"))
    )
    assert "def add" in result
    assert "syntax check ok" in result
    # Extract the fenced python block and parse it as real Python.
    fenced = result.split("```python", 1)[1].rsplit("```", 1)[0]
    ast.parse(fenced)


def test_codegen_debug_rejects_bad_name(tmp_path: Path) -> None:
    """An invalid function name is rejected, not generated."""
    result = asyncio.run(
        _skill("codegen_debug").handle(_ctx(tmp_path, "function 123bad a"))
    )
    assert "error" in result.lower()


def test_repo_docs_on_tmp_package(tmp_path: Path) -> None:
    """repo_docs documents a tmp package; markdown names the module."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "gizmo.py").write_text('"""Gizmo module."""\nVALUE = 42\n')

    result = asyncio.run(_skill("repo_docs").handle(_ctx(tmp_path, str(package))))
    assert "gizmo" in result
    assert "#" in result  # markdown output
