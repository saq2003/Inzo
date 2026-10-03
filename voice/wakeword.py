"""Wake-word detection stub (Rule 6: replaceable).

A real deployment plugs in openWakeWord/Porcupine via WakeWordDetector.
"""

from __future__ import annotations

from voice.protocols import AudioFrame


class StubWakeWordDetector:
    """Always-false detector unless a trigger payload is registered."""

    name = "stub-wakeword"

    def __init__(self, trigger: bytes | None = None) -> None:
        self._trigger = trigger

    def detect(self, frames: list[AudioFrame]) -> bool:
        if self._trigger is None:
            return False
        return self._trigger in b"".join(frames)
