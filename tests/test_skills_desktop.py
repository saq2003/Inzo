"""Desktop skill tests (offline, deterministic; no OS drivers are touched)."""

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


def test_file_organizer_preview_then_confirm_then_undo(tmp_path: Path) -> None:
    """Dry-run plans without moving; confirm moves; undo restores files."""
    messy = tmp_path / "messy"
    messy.mkdir()
    (messy / "photo.jpg").write_text("fake-jpeg")
    (messy / "notes.txt").write_text("hello")

    skill = _skill("file_organizer")

    preview = asyncio.run(skill.handle(_ctx(tmp_path, f"preview {messy}")))
    assert "dry-run" in preview
    assert "photo.jpg" in preview
    # Dry-run moved nothing.
    assert (messy / "photo.jpg").exists()

    done = asyncio.run(skill.handle(_ctx(tmp_path, f"organize {messy} confirm")))
    assert "moved 2 file(s)" in done
    assert not (messy / "photo.jpg").exists()

    undone = asyncio.run(skill.handle(_ctx(tmp_path, "undo")))
    assert "restored 2/2" in undone
    assert (messy / "photo.jpg").exists()
    assert (messy / "notes.txt").exists()


def test_file_organizer_empty_dir(tmp_path: Path) -> None:
    """An empty directory reports nothing to organize."""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = asyncio.run(_skill("file_organizer").handle(_ctx(tmp_path, f"preview {empty}")))
    assert "nothing to organize" in result


def test_clipboard_put_history_search(tmp_path: Path) -> None:
    """Clipboard put -> history -> search roundtrip."""
    skill = _skill("clipboard_history")
    stored = asyncio.run(skill.handle(_ctx(tmp_path, "put remember the milk")))
    assert "stored" in stored

    history = asyncio.run(skill.handle(_ctx(tmp_path, "history")))
    assert "remember the milk" in history

    hits = asyncio.run(skill.handle(_ctx(tmp_path, "search milk")))
    assert "remember the milk" in hits

    miss = asyncio.run(skill.handle(_ctx(tmp_path, "search zzzqxj")))
    assert "no entries matching" in miss


def test_hotkey_register_duplicate_conflict(tmp_path: Path) -> None:
    """Registering the same combo twice reports a conflict."""
    skill = _skill("hotkey")
    first = asyncio.run(
        skill.handle(_ctx(tmp_path, "register combo=ctrl+shift+a action=alpha"))
    )
    assert "registered" in first

    conflict = asyncio.run(
        skill.handle(_ctx(tmp_path, "register combo=ctrl+shift+a action=beta"))
    )
    assert "conflict" in conflict

    listed = asyncio.run(skill.handle(_ctx(tmp_path, "list")))
    assert "ctrl+shift+a" in listed


def test_gui_automation_invalid_action_rejected(tmp_path: Path) -> None:
    """A malformed gui action is rejected by validation, not executed."""
    result = asyncio.run(
        _skill("gui_automation").handle(_ctx(tmp_path, "gui.act bogus json"))
    )
    assert "rejected" in result.lower()


def test_gui_automation_without_driver_refused(tmp_path: Path) -> None:
    """A valid action with no driver adapter is refused honestly."""
    result = asyncio.run(
        _skill("gui_automation").handle(_ctx(tmp_path, "gui.act click x=100 y=200"))
    )
    assert "refused" in result.lower()
