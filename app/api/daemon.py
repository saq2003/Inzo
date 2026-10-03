"""Daemon control, notification inbox, and skill-run endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import dependencies
from security.permissions import PermissionDenied
from skills.base import SkillError
from skills.registry import UnknownSkillError

router = APIRouter()


class SkillRunRequest(BaseModel):
    """Body for ``POST /skills/run``."""

    skill: str = Field(min_length=1)
    message: str = ""
    actor: str = "user"


class SkillRunResponse(BaseModel):
    """Result of ``POST /skills/run``."""

    skill: str
    result: str


@router.get("/daemon/status")
async def daemon_status() -> dict[str, Any]:
    """Runtime status: skill counts, scheduler jobs, and queue depth."""
    registry = dependencies.get_skill_registry()
    scheduler = dependencies.get_scheduler()
    queue = dependencies.get_task_queue()
    return {
        "running": True,
        "skills": len(registry.all_skills()),
        "enabled_skills": len(registry.enabled_skills()),
        "scheduler_jobs": sorted(scheduler._jobs.keys()),
        "queue_depth": len(queue.list()),
    }


@router.get("/notifications/inbox")
async def notifications_inbox(
    limit: int = 50, unread_only: bool = False
) -> list[dict[str, Any]]:
    """Newest-first notification inbox entries."""
    center = dependencies.get_notification_center()
    return center.inbox_list(limit=max(1, min(limit, 500)), unread_only=unread_only)


@router.post("/skills/run", response_model=SkillRunResponse)
async def run_skill(request: SkillRunRequest) -> SkillRunResponse:
    """Run a registered skill as ``request.actor`` with ``request.message``."""
    engine = dependencies.get_skill_engine()
    try:
        result = await engine.run_skill(request.actor, request.skill, request.message)
    except UnknownSkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillRunResponse(skill=request.skill, result=result)
