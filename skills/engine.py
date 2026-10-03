"""Skill engine: permission-checked skill execution for the daemon/API.

Resolves a skill by name, enforces its required capabilities for the
calling actor, builds a :class:`SkillContext`, runs the skill, and emits a
``"skill.completed"`` event on the bus (best effort).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.logging_config import get_logger
from security.permissions import PermissionManager
from skills.base import Skill, SkillContext, SkillError
from skills.registry import SkillRegistry

logger = get_logger(__name__)


class SkillEngine:
    """Runs skills on behalf of actors with capability enforcement."""

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        permissions: PermissionManager,
        memory: Any,
        tools: Any,
        data_dir: Path,
        scheduler: Any = None,
        notifications: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._registry = registry
        self._permissions = permissions
        self._memory = memory
        self._tools = tools
        self._data_dir = data_dir
        self._scheduler = scheduler
        self._notifications = notifications
        self._event_bus = event_bus

    @property
    def registry(self) -> SkillRegistry:
        """The skill registry this engine executes from."""
        return self._registry

    async def run_skill(
        self, actor: str, skill_name: str, message: str = ""
    ) -> str:
        """Execute ``skill_name`` as ``actor`` with ``message``.

        Raises:
            UnknownSkillError: when ``skill_name`` is not registered.
            SkillError: when the skill is disabled.
            PermissionDenied: when ``actor`` lacks a required capability.
        """
        skill: Skill = self._registry.get(skill_name)
        if not self._registry.is_enabled(skill_name):
            raise SkillError(f"skill disabled: {skill_name}")
        for capability in skill.required_capabilities:
            self._permissions.require(actor, capability)

        context = SkillContext(
            actor=actor,
            message=message,
            memory=self._memory,
            tools=self._tools,
            data_dir=self._data_dir,
            scheduler=self._scheduler,
            notifications=self._notifications,
            event_bus=self._event_bus,
            permissions=self._permissions,
        )
        logger.info(
            "running skill", extra={"skill": skill_name, "actor": actor}
        )
        result = await skill.execute(context)

        if self._event_bus is not None:
            try:
                await self._event_bus.publish(
                    "skill.completed", {"skill": skill_name, "actor": actor}
                )
            except Exception:
                logger.exception(
                    "skill.completed event failed",
                    extra={"skill": skill_name},
                )
        return result
