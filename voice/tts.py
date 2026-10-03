"""Text-to-speech engines (Rule 6: replaceable).

``StubTTSEngine`` is deterministic and offline. Swap in Piper/Coqui or a
hosted TTS by implementing ``TTSEngine``.
"""

from __future__ import annotations

from app.logging_config import get_logger

logger = get_logger(__name__)


class StubTTSEngine:
    """Local TTS stub: returns silence placeholder bytes, logs the text."""

    name = "stub-tts"

    async def synthesize(self, text: str) -> bytes:
        logger.info("tts synthesize (stub)", extra={"chars": len(text)})
        # Real engines return 16-bit PCM; the stub returns empty bytes so
        # callers must handle "no audio produced" explicitly.
        return b""
