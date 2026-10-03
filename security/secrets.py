"""Secret handling: env-only, never hard-coded, never logged (Rule 5, 14)."""

from __future__ import annotations

import os


class SecretNotFoundError(Exception):
    """Raised when a required secret is missing from the environment."""


def get_secret(name: str, *, required: bool = False) -> str | None:
    """Read a secret from the environment.

    Returns None when absent and not required; raises SecretNotFoundError
    when required. Callers must never log the returned value.
    """
    value = os.environ.get(name)
    if value is None and required:
        raise SecretNotFoundError(f"required secret missing: {name}")
    return value


def mask_secret(value: str | None) -> str:
    """Return a safe-to-log masked representation of a secret."""
    if not value:
        return "<unset>"
    return f"<set:{len(value)} chars>"
