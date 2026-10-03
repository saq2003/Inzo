"""Health endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import HealthResponse
from inzo import __version__

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(app="INZO", version=__version__)
