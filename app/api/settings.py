"""Settings endpoints: view and update non-secret runtime settings."""

from __future__ import annotations

from fastapi import APIRouter

from app import dependencies
from app.logging_config import setup_logging
from app.schemas import SettingsUpdate, SettingsView

router = APIRouter()


@router.get("/api/settings", response_model=SettingsView)
async def view_settings() -> SettingsView:
    """View current (non-secret) settings."""
    settings = dependencies.get_settings()
    return SettingsView(
        app_name=settings.app_name,
        env=settings.env,
        log_level=settings.log_level,
        data_dir=str(settings.data_dir),
        host=settings.host,
        port=settings.port,
        llm_provider=settings.llm_provider,
        stt_confidence_threshold=settings.stt_confidence_threshold,
    )


@router.put("/api/settings", response_model=SettingsView)
async def update_settings(update: SettingsUpdate) -> SettingsView:
    """Update whitelisted runtime settings. Secrets are never settable here."""
    settings = dependencies.get_settings()
    # Settings is frozen; apply via object.__setattr__ on the cached instance.
    if update.log_level is not None:
        object.__setattr__(settings, "log_level", update.log_level.upper())
        setup_logging(settings.log_level)
    if update.stt_confidence_threshold is not None:
        object.__setattr__(
            settings, "stt_confidence_threshold", update.stt_confidence_threshold
        )
    return await view_settings()
