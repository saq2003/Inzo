"""Simple interval scheduler for recurring background jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.logging_config import get_logger

logger = get_logger(__name__)

JobFactory = Callable[[], Awaitable[None]]


class Scheduler:
    """Runs coroutine jobs on fixed intervals until stopped."""

    def __init__(self) -> None:
        self._jobs: dict[str, tuple[float, JobFactory]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._running = False

    def schedule(self, name: str, interval_s: float, factory: JobFactory) -> None:
        """Register ``factory`` to run every ``interval_s`` seconds."""
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        self._jobs[name] = (interval_s, factory)
        logger.info("job scheduled", extra={"job": name, "interval_s": interval_s})

    def start(self) -> None:
        """Start all scheduled jobs (idempotent)."""
        if self._running:
            return
        self._running = True
        for name, (interval_s, factory) in self._jobs.items():
            self._tasks[name] = asyncio.create_task(self._loop(name, interval_s, factory))

    async def _loop(self, name: str, interval_s: float, factory: JobFactory) -> None:
        while self._running:
            try:
                await factory()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduled job failed", extra={"job": name})
            await asyncio.sleep(interval_s)

    async def stop(self) -> None:
        """Stop all jobs."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
