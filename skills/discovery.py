"""Skill discovery: find ``Skill`` instances declared across the skills package.

Modules opt in by defining a module-level ``SKILLS`` list. Discovery is
defensive: a module that fails to import is logged and skipped so one
broken plugin can never break the registry.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

from skills.base import Skill

if TYPE_CHECKING:
    from skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


def discover_skill_instances() -> list[Skill]:
    """Import every module under the ``skills`` package and collect ``SKILLS``.

    Only module-level ``SKILLS`` attributes that are lists contribute;
    entries that are not :class:`Skill` instances are ignored. Modules that
    fail to import are logged (warning) and skipped.
    """
    from skills import __path__ as skills_path

    instances: list[Skill] = []
    for module_info in pkgutil.walk_packages(skills_path, prefix="skills."):
        try:
            module = importlib.import_module(module_info.name)
        except Exception as exc:
            logger.warning(
                "skipping skill module that failed to import",
                extra={"module": module_info.name, "error": str(exc)},
            )
            continue
        declared = getattr(module, "SKILLS", None)
        if not isinstance(declared, list):
            continue
        for item in declared:
            if isinstance(item, Skill):
                instances.append(item)
            else:
                logger.warning(
                    "ignoring non-Skill entry in SKILLS",
                    extra={"module": module_info.name, "entry": repr(item)[:120]},
                )
    logger.info("skill discovery finished", extra={"found": len(instances)})
    return instances


def build_skill_registry() -> SkillRegistry:
    """Build a registry with builtin skills plus discovered plugin skills.

    Discovered skills whose name collides with an already-registered skill
    are skipped with a warning (first registration wins).
    """
    from skills.builtin import builtin_skills
    from skills.registry import SkillRegistry

    registry = SkillRegistry()
    for skill in builtin_skills():
        registry.register(skill)
    for skill in discover_skill_instances():
        try:
            registry.register(skill)
        except ValueError as exc:
            logger.warning(
                "skipping duplicate skill name",
                extra={"skill": skill.name, "error": str(exc)},
            )
    return registry


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for skill in discover_skill_instances():
        print(f"{skill.name}: {skill.description}")
