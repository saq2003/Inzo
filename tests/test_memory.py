"""Memory subsystem tests: short-term, long-term, retrieval (offline)."""

from __future__ import annotations

import asyncio

from memory.short_term import ShortTermMemory


def test_short_term_fifo_and_cap():
    mem = ShortTermMemory(max_items=3)
    for i in range(5):
        mem.add("user", f"msg {i}")
    recent = mem.recent(10)
    assert [m.content for m in recent] == ["msg 2", "msg 3", "msg 4"]
    assert len(mem) == 3


def test_short_term_clear():
    mem = ShortTermMemory()
    mem.add("user", "hi")
    mem.clear()
    assert len(mem) == 0


def test_remember_and_recall_roundtrip(memory):
    async def _run():
        memory_id = await memory.remember(
            "user", "the launch code word is blueberry pancake", durable=True
        )
        assert memory_id
        hits = await memory.recall("what is the launch code word", limit=5)
        return hits

    hits = asyncio.run(_run())
    assert hits, "expected at least one recall hit"
    assert any("blueberry" in h.text for h in hits)


def test_recall_unrelated_returns_little(memory):
    async def _run():
        await memory.remember("user", "blueberry pancake launch code", durable=True)
        return await memory.recall("quantum chromodynamics lattice", limit=5)

    hits = asyncio.run(_run())
    # Vector scores for unrelated text should be zero/low; keyword none.
    assert all(h.score < 0.5 for h in hits)


def test_memory_stats(memory):
    async def _run():
        await memory.remember("user", "hello", durable=False)
        await memory.remember("user", "durable note", durable=True)

    asyncio.run(_run())
    stats = memory.stats()
    assert stats["short_term_items"] == 2
    assert stats["long_term_items"] == 1
    assert stats["vector_items"] == 1
