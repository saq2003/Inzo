"""Environment-variable configuration for INZO (Rule: env-var configuration).

No secrets are read at import time and nothing is hard-coded: every value
comes from the environment with a documented local-first default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable application settings loaded from the environment."""

    app_name: str = "INZO"
    env: str = "development"
    log_level: str = "INFO"
    data_dir: Path = Path("./data")
    host: str = "127.0.0.1"
    port: int = 8000
    llm_provider: str = "local-echo"
    stt_confidence_threshold: float = 0.6
    default_actor: str = "user"

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from ``INZO_*`` environment variables."""
        return cls(
            app_name=_env("INZO_APP_NAME", "INZO"),
            env=_env("INZO_ENV", "development"),
            log_level=_env("INZO_LOG_LEVEL", "INFO"),
            data_dir=Path(_env("INZO_DATA_DIR", "./data")),
            host=_env("INZO_HOST", "127.0.0.1"),
            port=_env_int("INZO_PORT", 8000),
            llm_provider=_env("INZO_LLM_PROVIDER", "local-echo"),
            stt_confidence_threshold=_env_float("INZO_STT_CONFIDENCE_THRESHOLD", 0.6),
            default_actor=_env("INZO_DEFAULT_ACTOR", "user"),
        )

    def ensure_data_dir(self) -> Path:
        """Create the data directory if missing and return it."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir
