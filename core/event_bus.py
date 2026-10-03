"""Async pub/sub event bus (Rule 6 — replaceable).

Topics are plain strings. Handlers run concurrently via ``asyncio.gather``;
a failing handler is logged and never breaks the other subscribers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.logging_config import get_logger

logger = get_logger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]

# Topics emitted across the daemon/API runtime.
TOPIC_TIME_TICK = "time.tick"
TOPIC_VOICE_COMMAND = "voice.command"
TOPIC_FILE_CHANGED = "file.changed"
TOPIC_NOTIFICATION = "notification"
TOPIC_SKILL_COMPLETED = "skill.completed"
TOPIC_ANOMALY_DETECTED = "anomaly.detected"


class EventBus:
    """In-process async publish/subscribe bus."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Register ``handler`` for ``topic`` (duplicate-safe: no-op)."""
        handlers = self._handlers.setdefault(topic, [])
        if handler not in handlers:
            handlers.append(handler)

    def unsubscribe(self, topic: str, handler: EventHandler) -> bool:
        """Remove ``handler`` from ``topic``; True when it was present."""
        handlers = self._handlers.get(topic)
        if not handlers or handler not in handlers:
            return False
        handlers.remove(handler)
        return True

    def subscribers(self, topic: str) -> int:
        """Return the number of handlers subscribed to ``topic``."""
        return len(self._handlers.get(topic, []))

    async def publish(
        self, topic: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Deliver ``payload`` to every subscriber of ``topic``.

        Handler exceptions are caught and logged individually so one bad
        subscriber cannot break the others or the publisher.
        """
        data: dict[str, Any] = dict(payload) if payload is not None else {}
        handlers = list(self._handlers.get(topic, []))
        if not handlers:
            return

        async def _deliver(handler: EventHandler) -> None:
            try:
                await handler(data)
            except Exception:
                logger.exception(
                    "event handler failed", extra={"topic": topic}
                )

        await asyncio.gather(*(_deliver(handler) for handler in handlers))
