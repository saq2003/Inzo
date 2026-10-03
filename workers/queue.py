"""Async background task queue (Rule 7).

``TaskQueue`` is the replaceable interface (Rule 6); ``InProcessQueue`` is
the local default running on the same event loop. CPU-heavy task bodies
must use ``run_in_executor`` (Rule 8).
"""

from __future__ import annotations

import asyncio
import enum
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from app.logging_config import get_logger

logger = get_logger(__name__)

TaskFactory = Callable[[], Awaitable[str]]


class TaskStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class TaskHandle:
    id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None


class TaskQueue(Protocol):
    """Replaceable background-task interface."""

    async def submit(self, name: str, factory: TaskFactory) -> TaskHandle: ...
    def get(self, task_id: str) -> TaskHandle | None: ...
    def list(self) -> list[TaskHandle]: ...


class InProcessQueue:
    """In-process asyncio task queue (local default)."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskHandle] = {}
        self._running: dict[str, asyncio.Task[None]] = {}

    async def submit(self, name: str, factory: TaskFactory) -> TaskHandle:
        handle = TaskHandle(id=str(uuid.uuid4()), name=name)
        self._tasks[handle.id] = handle

        async def _runner() -> None:
            handle.status = TaskStatus.RUNNING
            try:
                handle.result = await factory()
                handle.status = TaskStatus.DONE
            except Exception as exc:  # record, don't crash the loop
                handle.status = TaskStatus.FAILED
                handle.error = f"{type(exc).__name__}: {exc}"
                logger.exception("background task failed", extra={"task": handle.id})

        self._running[handle.id] = asyncio.create_task(_runner())
        logger.info("task submitted", extra={"task": handle.id, "task_name": name})
        return handle

    def get(self, task_id: str) -> TaskHandle | None:
        return self._tasks.get(task_id)

    def list(self) -> list[TaskHandle]:
        return list(self._tasks.values())

    async def shutdown(self) -> None:
        """Cancel outstanding runners (best effort)."""
        for task in self._running.values():
            task.cancel()
        self._running.clear()
