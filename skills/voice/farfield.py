"""Far-field listening skill: multi-mic SNR estimation and mic selection.

Real (deterministic, stdlib): :func:`snr_db` estimates the signal-to-noise
ratio of PCM frames by comparing the loudest decile of frame energies
(signal) against the quietest decile (noise); :func:`select_best_mic` picks
the mic with the best SNR. The mic array itself needs hardware, so it is
defined as :class:`FarfieldArray` with a stub that raises
:class:`AdapterNotConfiguredError` instead of fabricating audio.
"""

from __future__ import annotations

import math
import statistics
from typing import Protocol

from skills.base import Skill, SkillContext
from skills.voice.wakeword import AdapterNotConfiguredError, score_frame


def snr_db(frames: list[bytes]) -> float:
    """Estimate the SNR of PCM frames in decibels (deterministic, pure).

    Signal power is the mean square of the loudest decile of frames and
    noise power the mean square of the quietest decile; SNR = 10*log10(Ps/Pn).
    Returns 0.0 for empty input and ``inf`` when the noise floor is zero.

    Raises:
        ValueError: if ``frames`` is empty.
    """
    if not frames:
        raise ValueError("snr_db needs at least one frame")
    mean_squares = sorted(score_frame(frame) ** 2 for frame in frames)
    if not any(mean_squares):
        return 0.0
    decile = max(1, len(mean_squares) // 10)
    signal = statistics.fmean(mean_squares[-decile:])
    noise = statistics.fmean(mean_squares[:decile])
    if noise <= 0.0:
        return math.inf
    return 10.0 * math.log10(signal / noise)


def select_best_mic(mic_frames: dict[str, list[bytes]]) -> str:
    """Return the mic id with the best SNR estimate.

    Ties break alphabetically by mic id. Deterministic.

    Raises:
        ValueError: if ``mic_frames`` is empty.
    """
    if not mic_frames:
        raise ValueError("select_best_mic needs at least one mic")
    ranked = sorted(
        mic_frames.items(), key=lambda item: (-snr_db(item[1]), item[0])
    )
    return ranked[0][0]


class FarfieldArray(Protocol):
    """Plug-in point: far-field microphone array.

    A production adapter implements this against multi-mic hardware (e.g.
    ReSpeaker, USB array) with beamforming. Until configured, the skill
    raises instead of fabricating audio.
    """

    def select_beam(self, direction: float) -> None:
        """Steer the beam toward ``direction`` (degrees, 0-360)."""
        ...

    def capture(self) -> bytes:
        """Capture one raw PCM frame from the array."""
        ...


class StubFarfieldArray:
    """Far-field array stub: always reports that it is not configured."""

    def select_beam(self, direction: float) -> None:
        raise AdapterNotConfiguredError(
            "far-field array not configured: plug in a FarfieldArray adapter"
        )

    def capture(self) -> bytes:
        raise AdapterNotConfiguredError(
            "far-field array not configured: plug in a FarfieldArray adapter"
        )


class FarfieldListenSkill(Skill):
    """Far-field listening with SNR-based mic selection."""

    name = "farfield_listen"
    description = "Far-field capture with SNR-based microphone selection."
    intents = ("voice.farfield",)
    required_capabilities = ("skills.execute", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Needs hardware: a FarfieldArray adapter (multi-mic array with "
        "beamforming). Inject via FarfieldListenSkill(array=...)."
    )

    def __init__(self, array: FarfieldArray | None = None) -> None:
        self._array: FarfieldArray = array or StubFarfieldArray()

    async def handle(self, context: SkillContext) -> str:
        """Capture from the array, or report the missing adapter."""
        try:
            self._array.select_beam(0.0)
            frame = self._array.capture()
        except AdapterNotConfiguredError as exc:
            return f"farfield: {exc}"
        return f"farfield: captured {len(frame)} bytes (rms {score_frame(frame):.1f})"


SKILLS: list[Skill] = [FarfieldListenSkill()]
