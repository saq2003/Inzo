"""Speech-to-text engines (Rule 6: replaceable).

``StubSTTEngine`` is deterministic and offline: it returns scripted
transcripts for known frame payloads and — critically — low-confidence
empty results for anything unknown, so the pipeline asks for repetition
instead of fabricating speech.
"""

from __future__ import annotations

from app.logging_config import get_logger
from voice.protocols import AudioFrame, Transcription

logger = get_logger(__name__)


class StubSTTEngine:
    """Scriptable local STT stub implementing the STT engine protocol."""

    name = "stub-stt"

    def __init__(self, script: dict[bytes, Transcription] | None = None) -> None:
        # Maps exact frame payloads -> transcripts (used by tests/demos).
        self._script = script or {}

    async def transcribe(self, frames: list[AudioFrame]) -> Transcription:
        payload = b"".join(frames)
        if not payload:
            return Transcription(text="", confidence=0.0)
        hit = self._script.get(payload)
        if hit is not None:
            logger.info("stt scripted hit", extra={"confidence": hit.confidence})
            return hit
        # Unknown audio: do NOT guess. Report low confidence honestly.
        logger.info("stt unclear audio -> low confidence")
        return Transcription(text="", confidence=0.15)
