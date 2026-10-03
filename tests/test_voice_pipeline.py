"""Voice pipeline tests: VAD, confidence policy, no fabrication."""

from __future__ import annotations

import asyncio
import struct

import pytest

from voice.pipeline import NeedsRepetitionError, VoicePipeline, VoicePipelineConfig
from voice.protocols import Transcription
from voice.stt import StubSTTEngine
from voice.vad import EnergyVAD


def _loud_frame(value: int = 8000, samples: int = 320) -> bytes:
    """One 20ms 16-bit PCM mono frame at 16kHz with high energy."""
    return struct.pack(f"<{samples}h", *([value] * samples))


SILENCE = b"\x00" * 640


def test_vad_silence_vs_speech():
    vad = EnergyVAD()
    assert vad.is_speech(SILENCE) is False
    assert vad.is_speech(_loud_frame()) is True
    assert vad.is_speech(b"") is False


def test_pipeline_transcribes_confident_audio():
    frame = _loud_frame()
    stt = StubSTTEngine(script={frame: Transcription("hello inzo", 0.95)})
    pipeline = VoicePipeline(stt=stt)
    text, confidence = asyncio.run(pipeline.transcribe_frames([frame]))
    assert text == "hello inzo"
    assert confidence == pytest.approx(0.95)


def test_pipeline_never_fabricates_unclear_audio():
    # Unknown audio -> low confidence -> must ask for repetition, not guess.
    pipeline = VoicePipeline(stt=StubSTTEngine())
    with pytest.raises(NeedsRepetitionError):
        asyncio.run(pipeline.transcribe_frames([_loud_frame()]))


def test_pipeline_rejects_silence():
    pipeline = VoicePipeline(stt=StubSTTEngine())
    with pytest.raises(NeedsRepetitionError):
        asyncio.run(pipeline.transcribe_frames([SILENCE, SILENCE]))


def test_pipeline_low_confidence_script_asks_repetition():
    frame = _loud_frame()
    stt = StubSTTEngine(script={frame: Transcription("maybe hello", 0.2)})
    pipeline = VoicePipeline(
        stt=stt, config=VoicePipelineConfig(confidence_threshold=0.6, max_retries=0)
    )
    with pytest.raises(NeedsRepetitionError):
        asyncio.run(pipeline.transcribe_frames([frame]))


def test_synthesize_reply_returns_bytes():
    pipeline = VoicePipeline()
    audio = asyncio.run(pipeline.synthesize_reply("hello"))
    assert isinstance(audio, bytes)
