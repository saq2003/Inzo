"""INZO voice subsystem: replaceable audio pipeline (Rule 6)."""

from voice.pipeline import NeedsRepetitionError, VoicePipeline
from voice.protocols import VoiceResult

__all__ = ["NeedsRepetitionError", "VoicePipeline", "VoiceResult"]
