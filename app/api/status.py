"""System status endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter

from app import dependencies
from app.schemas import StatusResponse
from inzo import __version__

router = APIRouter()
_STARTED = time.monotonic()


@router.get("/api/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    """Runtime status: uptime, provider, and subsystem counts."""
    settings = dependencies.get_settings()
    memory = dependencies.get_memory_manager()
    stats = memory.stats()
    return StatusResponse(
        app=settings.app_name,
        version=__version__,
        env=settings.env,
        uptime_seconds=round(time.monotonic() - _STARTED, 1),
        llm_provider=settings.llm_provider,
        tools=len(dependencies.get_tool_registry().names()),
        skills=len(dependencies.get_skill_registry().all_skills()),
        memory_items=stats["long_term_items"],
        background_tasks=len(dependencies.get_task_queue().list()),
    )
