"""Energy-based voice activity detection (stdlib only, Rule 1).

A real deployment swaps in WebRTC VAD or a neural VAD via VADProtocol.
"""

from __future__ import annotations

import audioop

from voice.protocols import AudioFrame


class EnergyVAD:
    """RMS-energy VAD over 16-bit PCM mono frames."""

    def __init__(self, energy_threshold: int = 500, sample_width: int = 2) -> None:
        self.energy_threshold = energy_threshold
        self.sample_width = sample_width

    def is_speech(self, frame: AudioFrame) -> bool:
        """Return True when the frame's RMS energy exceeds the threshold."""
        if not frame:
            return False
        try:
            energy = audioop.rms(frame, self.sample_width)
        except audioop.error:
            return False
        return energy >= self.energy_threshold

    def segment(self, frames: list[AudioFrame]) -> list[AudioFrame]:
        """Keep only frames classified as speech."""
        return [f for f in frames if self.is_speech(f)]
