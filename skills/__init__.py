"""INZO skill system."""

from skills.base import Skill, SkillContext
from skills.builtin import builtin_skills
from skills.registry import SkillRegistry, UnknownSkillError

__all__ = [
    "Skill",
    "SkillContext",
    "SkillRegistry",
    "UnknownSkillError",
    "builtin_skills",
]
