"""Permission manager: deny-by-default capability checks (Rule 13).

Nothing is allowed unless explicitly granted. Tool execution always goes
through ``require()`` before running.
"""

from __future__ import annotations

from app.logging_config import get_logger

logger = get_logger(__name__)


class PermissionDenied(Exception):
    """Raised when an actor lacks a required capability."""


class PermissionManager:
    """Tracks granted capabilities per actor; deny-by-default."""

    def __init__(self) -> None:
        self._grants: dict[str, set[str]] = {}

    def grant(self, actor: str, capability: str) -> None:
        """Grant ``capability`` to ``actor``."""
        self._grants.setdefault(actor, set()).add(capability)
        logger.info("capability granted", extra={"actor": actor, "capability": capability})

    def revoke(self, actor: str, capability: str) -> bool:
        """Revoke ``capability`` from ``actor``; True if it was granted."""
        granted = self._grants.get(actor)
        if not granted or capability not in granted:
            return False
        granted.discard(capability)
        logger.info("capability revoked", extra={"actor": actor, "capability": capability})
        return True

    def check(self, actor: str, capability: str) -> bool:
        """Return True only if ``actor`` was explicitly granted ``capability``."""
        return capability in self._grants.get(actor, set())

    def require(self, actor: str, capability: str) -> None:
        """Raise PermissionDenied unless ``actor`` holds ``capability``."""
        if not self.check(actor, capability):
            logger.warning(
                "permission denied", extra={"actor": actor, "capability": capability}
            )
            raise PermissionDenied(
                f"actor '{actor}' lacks capability '{capability}'"
            )

    def capabilities(self, actor: str) -> list[str]:
        """List capabilities granted to ``actor``."""
        return sorted(self._grants.get(actor, set()))
