"""INZO application entrypoint: FastAPI factory + ``python -m app.main``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app import dependencies
from app.api import chat, health, memory, settings, skills, status, tasks, tools, voice
from app.config import Settings
from app.logging_config import get_logger, setup_logging
from inzo import __version__

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start/stop background services with the app."""
    scheduler = dependencies.get_scheduler()
    scheduler.start()
    logger.info("inzo started", extra={"version": __version__})
    yield
    await scheduler.stop()
    await dependencies.get_task_queue().shutdown()
    logger.info("inzo stopped")


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with all routers mounted."""
    if app_settings is not None:
        dependencies._singletons["settings"] = app_settings
    active = dependencies.get_settings()
    setup_logging(active.log_level)

    app = FastAPI(title="INZO", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(chat.router)
    app.include_router(voice.router)
    app.include_router(memory.router)
    app.include_router(tasks.router)
    app.include_router(skills.router)
    app.include_router(tools.router)
    app.include_router(settings.router)
    return app


def main() -> None:
    """Run the INZO API server (``python -m inzo`` / ``python -m app.main``)."""
    settings = dependencies.get_settings()
    setup_logging(settings.log_level)
    logger.info(
        "starting inzo",
        extra={"host": settings.host, "port": settings.port, "env": settings.env},
    )
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
