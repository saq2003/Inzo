"""INZO skill system: base types (Rule 6 — plugins are replaceable).

Skills are intent-triggered behaviors composed of tools, memory, and
intelligence modules. They never bypass the permission manager.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillContext:
    """What a skill may use during handling (injected by wiring)."""

    actor: str
    message: str
    memory: Any  # MemoryManager — typed loosely to avoid import cycles
    tools: Any  # ToolRegistry


class Skill(ABC):
    """Base class for skills. Subclass, set metadata, implement ``handle``."""

    name: str = "unnamed"
    description: str = ""
    intents: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ("skills.execute",)

    @abstractmethod
    async def handle(self, context: SkillContext) -> str:
        """Produce a response for the matched intent."""
        ...
