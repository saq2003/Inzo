"""Audio preprocessing stages (denoise / echo-cancel / enhance).

Local stubs document the interface. A real deployment plugs in
RNNoise/noisereduce, AEC, and spectral enhancement via AudioProcessor.
"""

from __future__ import annotations

from voice.protocols import AudioFrame, AudioProcessor


class PassthroughDenoiser:
    """No-op denoiser: documents the stage, changes nothing."""

    name = "passthrough-denoise"

    def process(self, frame: AudioFrame) -> AudioFrame:
        return frame


class PassthroughEchoCanceller:
    """No-op echo canceller: documents the stage, changes nothing."""

    name = "passthrough-aec"

    def process(self, frame: AudioFrame) -> AudioFrame:
        return frame


class PassthroughEnhancer:
    """No-op speech enhancer: documents the stage, changes nothing."""

    name = "passthrough-enhance"

    def process(self, frame: AudioFrame) -> AudioFrame:
        return frame


def preprocess(
    frames: list[AudioFrame], stages: list[AudioProcessor] | None = None
) -> list[AudioFrame]:
    """Run frames through each preprocessing stage in order."""
    active: list[AudioProcessor] = stages or [
        PassthroughDenoiser(),
        PassthroughEchoCanceller(),
        PassthroughEnhancer(),
    ]
    out = frames
    for stage in active:
        out = [stage.process(f) for f in out]
    return out
