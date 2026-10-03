"""INZO skill system: base types (Rule 6 — plugins are replaceable).

Skills are intent-triggered behaviors composed of tools, memory, and
intelligence modules. They never bypass the permission manager.
Background-first: every skill declares whether it can run headlessly
(``background``) and whether it is fully local (``local_only``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SkillError(Exception):
    """Raised for skill configuration or runtime contract violations."""


@dataclass(frozen=True)
class SkillContext:
    """What a skill may use during handling (injected by wiring)."""

    actor: str
    message: str
    memory: Any  # MemoryManager — typed loosely to avoid import cycles
    tools: Any  # ToolRegistry
    # Background-daemon wiring; set by SkillEngine, None in bare unit tests.
    data_dir: Path | None = None
    scheduler: Any = None  # workers.scheduler.Scheduler
    notifications: Any = None  # core.notifications.NotificationCenter
    event_bus: Any = None  # core.event_bus.EventBus
    permissions: Any = None  # security.permissions.PermissionManager


def require_data_dir(context: SkillContext) -> Path:
    """Return the skill data directory or raise SkillError."""
    if context.data_dir is None:
        raise SkillError("skill requires data_dir in SkillContext")
    return context.data_dir


class Skill(ABC):
    """Base class for skills. Subclass, set metadata, implement ``handle``."""

    name: str = "unnamed"
    description: str = ""
    intents: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ("skills.execute",)
    # Background-first metadata: all new skills default to headless-capable.
    background: bool = True
    # True when the skill runs fully locally on the stdlib. False means it
    # needs hardware, a model, or a network service via a Protocol adapter;
    # explain the plug-in point in ``adapter_note``.
    local_only: bool = True
    adapter_note: str = ""
    # Optional: seconds between background ticks; the daemon schedules
    # periodic execution for skills that set this (None = event-driven only).
    tick_interval_s: float | None = None

    @property
    def triggers(self) -> tuple[str, ...]:
        """Alias for ``intents`` (what the skill reacts to)."""
        return self.intents

    @property
    def capabilities(self) -> tuple[str, ...]:
        """Alias for ``required_capabilities``."""
        return self.required_capabilities

    @abstractmethod
    async def handle(self, context: SkillContext) -> str:
        """Produce a response for the matched intent."""
        ...

    async def execute(self, context: SkillContext, **kwargs: Any) -> str:
        """Background entry point used by SkillEngine; delegates to handle."""
        return await self.handle(context)
