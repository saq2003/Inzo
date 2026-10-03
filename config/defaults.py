"""Static default configuration values (overridable via environment)."""

from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "app_name": "INZO",
    "env": "development",
    "log_level": "INFO",
    "host": "127.0.0.1",
    "port": 8000,
    "llm_provider": "local-echo",
    "stt_confidence_threshold": 0.6,
    "short_term_max_items": 50,
    "tool_timeout_s": 10.0,
    "max_voice_retries": 1,
}
