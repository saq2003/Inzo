"""End-to-end agent workflow tests: message -> plan -> tools -> verify."""

from __future__ import annotations

import asyncio


def test_agent_calculate_end_to_end(agent):
    result = asyncio.run(agent.handle("calculate 12*12", actor="user"))
    assert result.intent == "calculate"
    assert "144" in result.reply
    assert result.verified is True
    assert result.issues == ()
    assert len(result.plan.steps) == 1


def test_agent_finance_end_to_end(agent):
    result = asyncio.run(
        agent.handle("compound principal=10000 rate=8 years=5", actor="user")
    )
    assert result.intent == "finance"
    assert "14,693.28" in result.reply or "14693" in result.reply
    assert result.verified is True


def test_agent_chat_no_tools(agent):
    result = asyncio.run(agent.handle("tell me a joke", actor="user"))
    assert result.intent == "chat"
    assert result.plan.steps == ()
    assert result.verified is True


def test_agent_unpermissioned_actor_gets_tool_failure_not_crash(agent):
    result = asyncio.run(agent.handle("calculate 1+1", actor="intruder"))
    assert result.intent == "calculate"
    # Permission denial is captured as a tool failure line, not an exception.
    assert any("failed" in line for line in result.tool_outputs)
    assert result.verified is True


def test_agent_remembers_conversation(agent):
    async def _run():
        await agent.handle("my favorite color is teal", actor="user")
        turns = agent.memory.recent_turns(4)
        return turns

    turns = asyncio.run(_run())
    assert any("teal" in t.content for t in turns)
