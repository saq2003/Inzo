"""Research skill tests (offline, deterministic; no network fetches)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from skills.base import Skill, SkillContext
from skills.discovery import build_skill_registry
from skills.research.video_summary import summarize_text


def _ctx(tmp_path: Path, message: str) -> SkillContext:
    """Bare skill context over an isolated data dir."""
    return SkillContext(
        actor="test", message=message, memory=None, tools=None, data_dir=tmp_path
    )


def _skill(name: str) -> Skill:
    """Fetch a skill from a fresh registry."""
    return build_skill_registry().get(name)


_SAMPLE_TEXT = (
    "Photosynthesis converts light energy into chemical energy. "
    "Chlorophyll absorbs red and blue light most strongly. "
    "Water is split in the thylakoid membrane to release oxygen. "
    "The Calvin cycle fixes carbon dioxide into sugar. "
    "Stomata regulate gas exchange in leaves. "
    "Rubisco is the most abundant enzyme on Earth. "
    "C4 plants concentrate CO2 for efficiency in hot climates. "
    "Light reactions produce ATP and NADPH for the dark reactions."
)


def test_study_notes_sections_present(tmp_path: Path) -> None:
    """Study notes on sample text contain the expected sections."""
    result = asyncio.run(_skill("study_notes").handle(_ctx(tmp_path, _SAMPLE_TEXT)))
    assert "Study notes" in result
    assert "Key points:" in result
    assert "Glossary:" in result


def test_study_notes_needs_minimum_text(tmp_path: Path) -> None:
    """Too-short input gets the usage message."""
    result = asyncio.run(_skill("study_notes").handle(_ctx(tmp_path, "tiny")))
    assert "usage" in result


def test_video_summary_pure_function_bounded() -> None:
    """summarize_text returns at most n sentences, in original order."""
    summary = summarize_text(_SAMPLE_TEXT, n=3)
    assert isinstance(summary, list)
    assert 1 <= len(summary) <= 3
    for sentence in summary:
        assert sentence in _SAMPLE_TEXT


def test_doc_qa_index_then_ask(tmp_path: Path) -> None:
    """Indexing a tmp dir and asking finds the planted content."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "notes.txt").write_text(
        "The quick brown fox explains photosynthesis in plants."
    )

    skill = _skill("doc_qa")
    indexed = asyncio.run(skill.handle(_ctx(tmp_path, "index docs")))
    assert "indexed 1 file" in indexed

    answer = asyncio.run(skill.handle(_ctx(tmp_path, "ask what does the fox explain")))
    assert "photosynthesis" in answer
