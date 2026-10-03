"""Background worker tests: queue lifecycle and scheduler."""

from __future__ import annotations

import asyncio

from workers.queue import InProcessQueue, TaskStatus
from workers.scheduler import Scheduler


def test_queue_completes_task():
    async def _run():
        queue = InProcessQueue()

        async def _work() -> str:
            await asyncio.sleep(0.01)
            return "done-ok"

        handle = await queue.submit("demo", _work)
        for _ in range(100):
            current = queue.get(handle.id)
            assert current is not None
            if current.status in (TaskStatus.DONE, TaskStatus.FAILED):
                break
            await asyncio.sleep(0.02)
        final = queue.get(handle.id)
        assert final is not None
        assert final.status == TaskStatus.DONE
        assert final.result == "done-ok"
        await queue.shutdown()

    asyncio.run(_run())


def test_queue_records_failure():
    async def _run():
        queue = InProcessQueue()

        async def _boom() -> str:
            raise RuntimeError("kaput")

        handle = await queue.submit("boom", _boom)
        for _ in range(100):
            if queue.get(handle.id).status == TaskStatus.FAILED:  # type: ignore[union-attr]
                break
            await asyncio.sleep(0.02)
        final = queue.get(handle.id)
        assert final is not None
        assert final.status == TaskStatus.FAILED
        assert "kaput" in (final.error or "")
        await queue.shutdown()

    asyncio.run(_run())


def test_scheduler_runs_job():
    async def _run():
        calls = 0
        scheduler = Scheduler()

        async def _job() -> None:
            nonlocal calls
            calls += 1

        scheduler.schedule("tick", 0.05, _job)
        scheduler.start()
        await asyncio.sleep(0.22)
        await scheduler.stop()
        assert calls >= 2

    asyncio.run(_run())


def test_scheduler_rejects_bad_interval():
    scheduler = Scheduler()

    async def _job() -> None:
        pass

    try:
        scheduler.schedule("bad", 0, _job)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
