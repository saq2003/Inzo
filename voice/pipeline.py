"""Voice pipeline: capture -> VAD -> preprocess -> STT -> agent -> TTS.

Pipeline order per spec:
Microphone -> Audio Capture -> VAD -> Noise Reduction -> Echo Cancellation
-> Speech Enhancement -> STT -> NLP -> Agent Core -> Tool/Skill Execution
-> TTS -> Audio Output.

Confidence policy: when transcription confidence is below threshold, the
pipeline retries once after re-preprocessing; if still low it sets
``needs_repetition`` so INZO asks the speaker to repeat — it never
fabricates missing speech.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.logging_config import get_logger
from voice.denoise import preprocess
from voice.protocols import AudioFrame, AudioProcessor, STTEngine, TTSEngine, VADProtocol
from voice.stt import StubSTTEngine
from voice.tts import StubTTSEngine
from voice.vad import EnergyVAD

logger = get_logger(__name__)


class NeedsRepetitionError(Exception):
    """Raised when audio is too unclear to transcribe confidently."""


@dataclass
class VoicePipelineConfig:
    confidence_threshold: float = 0.6
    max_retries: int = 1


class VoicePipeline:
    """Chains the voice stages; engines are injected (Rule 6)."""

    def __init__(
        self,
        *,
        vad: VADProtocol | None = None,
        preprocessors: list[AudioProcessor] | None = None,
        stt: STTEngine | None = None,
        tts: TTSEngine | None = None,
        config: VoicePipelineConfig | None = None,
    ) -> None:
        self.vad = vad or EnergyVAD()
        self.preprocessors = preprocessors or []
        self.stt = stt or StubSTTEngine()
        self.tts = tts or StubTTSEngine()
        self.config = config or VoicePipelineConfig()

    async def transcribe_frames(self, frames: list[AudioFrame]) -> tuple[str, float]:
        """Run VAD -> preprocess -> STT with the confidence/retry policy.

        Returns (transcript, confidence). Raises NeedsRepetitionError when
        the audio cannot be transcribed confidently.
        """
        speech = [f for f in frames if self.vad.is_speech(f)]
        logger.info(
            "vad segmented",
            extra={"total": len(frames), "speech": len(speech)},
        )
        if not speech:
            raise NeedsRepetitionError("no speech detected; please repeat")

        cleaned = preprocess(speech, self.preprocessors or None)
        attempts = 0
        while True:
            result = await self.stt.transcribe(cleaned)
            logger.info(
                "stt result",
                extra={"confidence": result.confidence, "attempt": attempts},
            )
            if result.confidence >= self.config.confidence_threshold and result.text:
                return result.text, result.confidence
            attempts += 1
            if attempts > self.config.max_retries:
                raise NeedsRepetitionError(
                    f"low transcription confidence ({result.confidence:.2f}); "
                    "please repeat more clearly"
                )
            # Retry: re-run preprocessing (a real engine would re-capture).
            cleaned = preprocess(cleaned, self.preprocessors or None)

    async def synthesize_reply(self, text: str) -> bytes:
        """Synthesize reply audio for ``text``."""
        return await self.tts.synthesize(text)
