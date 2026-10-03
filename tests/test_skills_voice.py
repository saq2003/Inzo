"""Voice skill tests (offline, deterministic).

Pure functions are tested directly; adapter-only skills are tested through
their honest "not configured" path (no hardware is ever touched).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from skills.base import Skill, SkillContext
from skills.discovery import build_skill_registry
from skills.voice.emotion import dominant, score_emotion
from skills.voice.multilingual import normalize_hinglish


def _ctx(tmp_path: Path, message: str) -> SkillContext:
    """Bare skill context over an isolated data dir."""
    return SkillContext(
        actor="test", message=message, memory=None, tools=None, data_dir=tmp_path
    )


def _skill(name: str) -> Skill:
    """Fetch a skill from a fresh registry."""
    return build_skill_registry().get(name)


def test_normalize_hinglish_devanagari() -> None:
    """Devanagari input normalizes to romanized Hinglish."""
    assert "nahin" in normalize_hinglish("मैं नहीं जानता")


def test_normalize_hinglish_variant_collapse() -> None:
    """Case, punctuation, and whitespace collapse to a canonical form."""
    assert normalize_hinglish("MEIN   NAHIN!! jaanta") == "mein nahin jaanta"


def test_emotion_dominant_joy() -> None:
    """'main bahut khush hoon' reads as joy."""
    assert dominant("main bahut khush hoon") == "joy"


def test_emotion_neutral_when_nothing_matches() -> None:
    """Text with no lexicon words scores neutral."""
    assert dominant("the cat sat on the mat") == "neutral"
    scores = score_emotion("the cat sat on the mat")
    assert sum(scores.values()) == 0.0


def test_emotion_scores_normalized() -> None:
    """Scores sum to 1.0 when lexicon words match."""
    scores = score_emotion("main bahut khush hoon aur thoda udaas")
    assert scores["joy"] > 0.0
    assert scores["sadness"] > 0.0
    assert abs(sum(scores.values()) - 1.0) < 1e-9


def test_wakeword_without_adapter_reports_not_configured(tmp_path: Path) -> None:
    """Wakeword handle() with no mic adapter says it is not configured."""
    result = asyncio.run(_skill("wakeword").handle(_ctx(tmp_path, "")))
    assert "configur" in result.lower()


def test_speaker_id_without_adapter_reports_not_configured(tmp_path: Path) -> None:
    """Speaker-id identify with no embedder adapter says it is not configured."""
    result = asyncio.run(_skill("speaker_id").handle(_ctx(tmp_path, "identify")))
    assert "configur" in result.lower()


def test_voice_clone_without_adapter_reports_not_configured(tmp_path: Path) -> None:
    """Voice-clone enroll with no engine adapter says it is not configured."""
    result = asyncio.run(
        _skill("voice_clone").handle(_ctx(tmp_path, "enroll: demo consent=yes"))
    )
    assert "configur" in result.lower()


def test_voice_multilingual_handle_normalizes(tmp_path: Path) -> None:
    """The voice_multilingual skill handle() returns normalized text."""
    result = asyncio.run(
        _skill("voice_multilingual").handle(_ctx(tmp_path, "मैं नहीं जानता"))
    )
    assert "nahin" in result
