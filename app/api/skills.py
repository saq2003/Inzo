"""Skill endpoints: list, enable, disable."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import dependencies
from app.schemas import SkillInfo
from skills.registry import SkillRegistry, UnknownSkillError

router = APIRouter()


def _info(registry: SkillRegistry, name: str) -> SkillInfo:
    skill = registry.get(name)
    return SkillInfo(
        name=skill.name,
        description=skill.description,
        intents=list(skill.intents),
        enabled=registry.is_enabled(name),
    )


@router.get("/api/skills", response_model=list[SkillInfo])
async def list_skills() -> list[SkillInfo]:
    """List all registered skills and their enabled state."""
    registry = dependencies.get_skill_registry()
    return [_info(registry, s.name) for s in registry.all_skills()]


@router.post("/api/skills/{name}/enable", response_model=SkillInfo)
async def enable_skill(name: str) -> SkillInfo:
    """Enable a skill."""
    registry = dependencies.get_skill_registry()
    try:
        registry.enable(name)
    except UnknownSkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _info(registry, name)


@router.post("/api/skills/{name}/disable", response_model=SkillInfo)
async def disable_skill(name: str) -> SkillInfo:
    """Disable a skill."""
    registry = dependencies.get_skill_registry()
    try:
        registry.disable(name)
    except UnknownSkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _info(registry, name)
