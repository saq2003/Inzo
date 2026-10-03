"""Computer-vision pipeline (Rule 6: replaceable).

``StubVisionAnalyzer`` documents the interface for local development.
Swap in a transformers/CLIP/YOLO adapter by implementing VisionAnalyzer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class VisionResult:
    description: str
    labels: tuple[str, ...] = ()
    confidence: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


class VisionAnalyzer(Protocol):
    """Image analysis interface."""

    name: str

    async def analyze(self, image: bytes, *, timeout_s: float = 30.0) -> VisionResult:
        """Analyze raw image bytes. Must honor ``timeout_s`` (Rule 9)."""
        ...


class StubVisionAnalyzer:
    """Deterministic stub: reports image size, never invents content."""

    name = "stub-vision"

    async def analyze(self, image: bytes, *, timeout_s: float = 30.0) -> VisionResult:
        logger.info("vision analyze (stub)", extra={"bytes": len(image)})
        return VisionResult(
            description=(
                "vision engine not configured; received "
                f"{len(image)} bytes of image data (stub)"
            ),
            labels=(),
            confidence=0.0,
        )
