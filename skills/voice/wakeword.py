"""Wake-word listening skill: energy gate + pluggable keyword spotter.

Real (deterministic, stdlib): ``score_frame`` converts 16-bit PCM mono bytes
to an RMS energy value and ``energy_gate`` decides whether the frame passes a
noise threshold. The RMS math is equivalent to ``audioop.rms`` but is
implemented with ``struct`` + ``statistics`` because ``audioop`` is deprecated
in Python 3.12.

Hardware (not configured): actual microphone capture and keyword spotting are
defined as protocols below. :class:`StubMicrophone` / :class:`StubKeywordSpotter`
raise :class:`AdapterNotConfiguredError` so the skill never fakes a detection.
"""

from __future__ import annotations

import statistics
import struct
from typing import Protocol

from skills.base import Skill, SkillContext, require_data_dir


class AdapterNotConfiguredError(RuntimeError):
    """Raised when a hardware adapter is required but not configured."""


def score_frame(frame: bytes, *, sample_width: int = 2) -> float:
    """Return the RMS energy of a PCM audio frame (deterministic).

    Args:
        frame: raw PCM bytes (mono).
        sample_width: bytes per sample; only 2 (16-bit) is supported.

    Returns:
        Root-mean-square sample amplitude, 0.0 for empty/silent frames.

    Raises:
        ValueError: if ``sample_width`` is not 2.
    """
    if sample_width != 2:
        raise ValueError(f"unsupported sample_width: {sample_width}")
    if not frame:
        return 0.0
    count = len(frame) // 2
    if count == 0:
        return 0.0
    samples = struct.unpack(f"<{count}h", frame[: count * 2])
    mean_square = statistics.fmean(s * s for s in samples)
    return float(mean_square**0.5)


def energy_gate(frames: list[bytes], *, threshold: float = 500.0) -> list[bool]:
    """Apply the energy gate to frames: True where RMS >= threshold."""
    return [score_frame(frame) >= threshold for frame in frames]


class MicrophoneProtocol(Protocol):
    """Plug-in point: real microphone capture for wake-word listening.

    A production adapter implements this against a mic device (e.g. PyAudio,
    sounddevice) and is injected into :class:`WakewordSkill`. Until then the
    skill reports that the adapter is not configured instead of fabricating
    detections.
    """

    def capture_frames(self, *, duration_s: float) -> list[bytes]:
        """Capture raw PCM frames from the microphone."""
        ...


class KeywordSpotter(Protocol):
    """Plug-in point: keyword-spotting engine for the wake phrase.

    A production adapter implements this (e.g. openWakeWord, Porcupine) and is
    injected into :class:`WakewordSkill`.
    """

    def detect(self, frames: list[bytes]) -> bool:
        """Return True when the wake phrase is present in the frames."""
        ...


class StubMicrophone:
    """Microphone adapter stub: always reports that it is not configured."""

    def capture_frames(self, *, duration_s: float) -> list[bytes]:
        raise AdapterNotConfiguredError(
            "microphone capture not configured: plug in a MicrophoneProtocol adapter"
        )


class StubKeywordSpotter:
    """Keyword-spotter stub: always reports that it is not configured."""

    def detect(self, frames: list[bytes]) -> bool:
        raise AdapterNotConfiguredError(
            "keyword spotting not configured: plug in a KeywordSpotter adapter"
        )


class WakewordSkill(Skill):
    """Listens for the wake phrase using an energy gate + keyword spotter."""

    name = "wakeword"
    description = "Energy-gated wake-word listening with a pluggable keyword spotter."
    intents = ("wakeword.listen",)
    required_capabilities = ("skills.execute", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Needs hardware: a MicrophoneProtocol adapter for capture and a "
        "KeywordSpotter adapter (openWakeWord/Porcupine) for the wake phrase. "
        "Inject via WakewordSkill(microphone=..., spotter=...)."
    )

    def __init__(
        self,
        microphone: MicrophoneProtocol | None = None,
        spotter: KeywordSpotter | None = None,
    ) -> None:
        self._microphone: MicrophoneProtocol = microphone or StubMicrophone()
        self._spotter: KeywordSpotter = spotter or StubKeywordSpotter()

    async def handle(self, context: SkillContext) -> str:
        """Run the energy gate over captured frames, then keyword spotting.

        Without a configured adapter this reports the missing hardware
        instead of fabricating a detection.
        """
        _ = require_data_dir(context)
        try:
            frames = self._microphone.capture_frames(duration_s=2.0)
        except AdapterNotConfiguredError as exc:
            return f"wakeword: {exc}"
        if not frames:
            return "wakeword: captured no frames"
        gate = energy_gate(frames)
        voiced = sum(gate)
        if voiced == 0:
            return "wakeword: only silence detected (no frames passed the energy gate)"
        try:
            detected = self._spotter.detect([f for f, g in zip(frames, gate, strict=True) if g])
        except AdapterNotConfiguredError as exc:
            return (
                f"wakeword: {voiced}/{len(frames)} frames passed the energy gate; {exc}"
            )
        return f"wakeword detected: {detected} ({voiced}/{len(frames)} voiced frames)"


SKILLS: list[Skill] = [WakewordSkill()]
