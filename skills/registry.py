"""Skill registry: registration, enable/disable, intent matching."""

from __future__ import annotations

from app.logging_config import get_logger
from skills.base import Skill

logger = get_logger(__name__)


class UnknownSkillError(KeyError):
    """Raised when a skill name is not registered."""


class SkillRegistry:
    """Holds skills; only enabled skills can match intents."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._enabled: set[str] = set()

    def register(self, skill: Skill, *, enabled: bool = True) -> None:
        """Register a skill; enabled by default."""
        if not skill.name or skill.name in self._skills:
            raise ValueError(f"invalid or duplicate skill name: {skill.name!r}")
        self._skills[skill.name] = skill
        if enabled:
            self._enabled.add(skill.name)
        logger.info("skill registered", extra={"skill": skill.name, "enabled": enabled})

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise UnknownSkillError(f"unknown skill: {name}") from exc

    def enable(self, name: str) -> None:
        self.get(name)
        self._enabled.add(name)

    def disable(self, name: str) -> None:
        self.get(name)
        self._enabled.discard(name)

    def is_enabled(self, name: str) -> bool:
        return name in self._enabled

    def enabled_skills(self) -> list[Skill]:
        return [self._skills[name] for name in sorted(self._enabled)]

    def all_skills(self) -> list[Skill]:
        return [self._skills[name] for name in sorted(self._skills)]

    def match(self, intent: str) -> Skill | None:
        """Return the first enabled skill whose intents include ``intent``."""
        for skill in self.enabled_skills():
            if intent in skill.intents:
                return skill
        return None
