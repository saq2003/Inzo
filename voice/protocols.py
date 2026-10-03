"""Voice engine protocols: every stage is swappable (Rule 3, Rule 6).

Local-first stubs implement these for development; production engines
(Whisper/Vosk for STT, Piper/Coqui for TTS, WebRTC VAD, RNNoise, …)
plug in by implementing the same protocols.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# 16-bit PCM mono audio frames; engines agree on sample rate out-of-band.
AudioFrame = bytes


@dataclass(frozen=True)
class Transcription:
    text: str
    confidence: float  # 0.0 .. 1.0
    language: str = "en"


@dataclass(frozen=True)
class VoiceResult:
    transcript: str
    confidence: float
    needs_repetition: bool
    reply_text: str = ""
    reply_audio: bytes = b""


class VADProtocol(Protocol):
    """Voice activity detection: is this frame speech?"""

    def is_speech(self, frame: AudioFrame) -> bool: ...


class AudioProcessor(Protocol):
    """A preprocess stage: denoise, echo-cancel, enhance."""

    name: str

    def process(self, frame: AudioFrame) -> AudioFrame: ...


class STTEngine(Protocol):
    """Speech-to-text engine."""

    name: str

    async def transcribe(self, frames: list[AudioFrame]) -> Transcription:
        """Transcribe frames. Must never fabricate: return low confidence
        (or empty text) when the audio is unclear."""
        ...


class TTSEngine(Protocol):
    """Text-to-speech engine."""

    name: str

    async def synthesize(self, text: str) -> bytes:
        """Synthesize PCM audio for ``text``."""
        ...


class WakeWordDetector(Protocol):
    """Wake-word spotting over a frame window."""

    name: str

    def detect(self, frames: list[AudioFrame]) -> bool: ...
