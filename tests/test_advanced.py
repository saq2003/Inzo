"""Advanced skill tests (offline, deterministic)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from skills.advanced.anomaly_detect import zscore_anomalies
from skills.advanced.conv_summarizer import summarize
from skills.advanced.lan_sync import SyncProtocol
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


def test_autonomous_goals_add_then_status_shows_percent(tmp_path: Path) -> None:
    """An added goal shows up in status with a completion percentage."""
    skill = _skill("autonomous_goals")
    added = asyncio.run(skill.handle(_ctx(tmp_path, "add water the plants daily")))
    assert "added" in added.lower() or "goal" in added.lower()

    status = asyncio.run(skill.handle(_ctx(tmp_path, "status")))
    assert "%" in status
    assert "plants" in status


def test_self_learn_never_do_lists_rule(tmp_path: Path) -> None:
    """'never do X' is remembered and shows in 'rules'."""
    skill = _skill("self_learn")
    learned = asyncio.run(
        skill.handle(_ctx(tmp_path, "never do deployments on fridays"))
    )
    assert "rule" in learned.lower() or "learned" in learned.lower()

    rules = asyncio.run(skill.handle(_ctx(tmp_path, "rules")))
    assert "deployments on fridays" in rules


def test_workflow_macros_define_json_and_run(tmp_path: Path) -> None:
    """A JSON macro with a time step runs and returns the time output."""
    skill = _skill("workflow_macros")
    body = json.dumps({"steps": [{"skill": "time", "message": ""}]})
    defined = asyncio.run(skill.handle(_ctx(tmp_path, f"define morning\n{body}")))
    assert "defined" in defined

    ran = asyncio.run(skill.handle(_ctx(tmp_path, "run morning")))
    assert "current time" in ran


def test_anomaly_detect_zscore_flags_outlier() -> None:
    """A crafted series with one spike flags exactly that index."""
    values = [10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 50.0, 10.1, 9.7, 10.2]
    anomalies = zscore_anomalies(values)
    assert anomalies == [6]
    assert zscore_anomalies([1.0, 1.0, 1.0]) == []


def test_conv_summarizer_bounded_output(tmp_path: Path) -> None:
    """Summarizing a 10-sentence text returns at most 5 sentences."""
    text = " ".join(f"Sentence number {i} talks about the weather." for i in range(10))
    summary = summarize(text)
    assert 1 <= len(summary) <= 5

    skill = _skill("conv_summarizer")
    result = asyncio.run(skill.handle(_ctx(tmp_path, f"summarize {text}")))
    assert result.strip()


def test_lan_sync_loopback_roundtrip() -> None:
    """An advertise envelope survives serialize -> parse unchanged."""
    envelope = SyncProtocol.advertise("node-1", capabilities=["sync"])
    raw = SyncProtocol.to_bytes(envelope)
    back = SyncProtocol.parse(raw)
    assert back.node_id == "node-1"
    assert back.kind == "advertise"
    assert back.payload["capabilities"] == ["sync"]


def test_lan_sync_skill_advertise(tmp_path: Path) -> None:
    """The lan_sync skill advertises an envelope through handle()."""
    result = asyncio.run(_skill("lan_sync").handle(_ctx(tmp_path, "advertise")))
    assert "advertise envelope" in result
    assert "node_id=" in result


def test_skill_marketplace_index_then_verify(tmp_path: Path) -> None:
    """Indexing a tmp plugin dir then verifying it reports ok."""
    plugin = tmp_path / "src" / "demo_plugin"
    plugin.mkdir(parents=True)
    (plugin / "skill.json").write_text(
        json.dumps({"name": "demo", "version": "0.1.0"})
    )
    (plugin / "skill.py").write_text('"""Demo plugin."""\n')

    skill = _skill("skill_marketplace")
    indexed = asyncio.run(skill.handle(_ctx(tmp_path, f"index {plugin}")))
    assert "indexed" in indexed

    index_path = tmp_path / "marketplace" / "demo.index.json"
    verified = asyncio.run(
        skill.handle(_ctx(tmp_path, f"verify {index_path} {plugin}"))
    )
    assert "ok" in verified.lower()
    assert "mismatched: 0" in verified
