"""Realtime voice-turn skill: barge-in state machine for live conversation.

Real (deterministic, stdlib): :class:`RealtimeTurn` is a pure state machine
(IDLE → LISTENING → RESPONDING, with USER_INTERRUPT for barge-in) driven by
voice-activity events and partial transcripts. Streaming STT itself needs a
model engine, so it is defined as :class:`StreamingSTT` with a stub that
raises :class:`AdapterNotConfiguredError` instead of fabricating transcripts.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from skills.base import Skill, SkillContext


class AdapterNotConfiguredError(RuntimeError):
    """Raised when a streaming-STT adapter is required but not configured."""


class TurnState(StrEnum):
    """Barge-in turn states."""

    IDLE = "idle"
    LISTENING = "listening"
    USER_INTERRUPT = "user_interrupt"
    RESPONDING = "responding"


class RealtimeTurn:
    """Pure, deterministic turn state machine for realtime voice.

    Transitions:
    - IDLE --speech--> LISTENING
    - LISTENING --interrupt()--> USER_INTERRUPT
    - LISTENING --begin_response()--> RESPONDING
    - RESPONDING --speech (barge-in)--> USER_INTERRUPT
    - RESPONDING --response_done()--> IDLE
    - USER_INTERRUPT --speech--> LISTENING
    - USER_INTERRUPT --begin_response()--> RESPONDING
    """

    def __init__(self) -> None:
        self._state = TurnState.IDLE
        self._partials: list[str] = []

    @property
    def state(self) -> TurnState:
        """Current turn state."""
        return self._state

    @property
    def partials(self) -> list[str]:
        """Partial transcripts collected during this turn."""
        return list(self._partials)

    def on_audio_event(self, is_speech: bool) -> TurnState:
        """Feed a voice-activity event; returns the new state."""
        if is_speech:
            if self._state in (TurnState.IDLE, TurnState.USER_INTERRUPT):
                self._state = TurnState.LISTENING
            elif self._state == TurnState.RESPONDING:
                # Barge-in: user speaks over the assistant.
                self._state = TurnState.USER_INTERRUPT
        return self._state

    def on_partial(self, text: str) -> TurnState:
        """Feed a partial transcript; returns the new state."""
        cleaned = text.strip()
        if cleaned:
            self._partials.append(cleaned)
            if self._state == TurnState.IDLE:
                self._state = TurnState.LISTENING
        return self._state

    def interrupt(self) -> TurnState:
        """User interruption; returns the new state."""
        if self._state in (TurnState.LISTENING, TurnState.RESPONDING):
            self._state = TurnState.USER_INTERRUPT
        return self._state

    def begin_response(self) -> TurnState:
        """Assistant starts responding; returns the new state."""
        if self._state in (TurnState.LISTENING, TurnState.USER_INTERRUPT):
            self._state = TurnState.RESPONDING
            self._partials.clear()
        return self._state

    def response_done(self) -> TurnState:
        """Assistant finished responding; returns the new state."""
        if self._state == TurnState.RESPONDING:
            self._state = TurnState.IDLE
        return self._state

    def reset(self) -> TurnState:
        """Return to IDLE and clear partials."""
        self._state = TurnState.IDLE
        self._partials.clear()
        return self._state


class StreamingSTT(Protocol):
    """Plug-in point: streaming speech-to-text engine.

    A production adapter implements this with a streaming model (e.g.
    Whisper streaming, Vosk, Deepgram). Until configured, the skill raises
    instead of fabricating transcripts.
    """

    async def transcribe_stream(self) -> str:
        """Run one realtime STT session; returns the final transcript."""
        ...


class StubStreamingSTT:
    """Streaming-STT stub: always reports that it is not configured."""

    async def transcribe_stream(self) -> str:
        raise AdapterNotConfiguredError(
            "streaming STT not configured: plug in a StreamingSTT adapter"
        )


class RealtimeVoiceSkill(Skill):
    """Runs realtime voice turns with barge-in handling."""

    name = "voice_realtime"
    description = "Realtime voice turn manager with barge-in interruption handling."
    intents = ("voice.realtime",)
    required_capabilities = ("skills.execute", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Needs hardware/model: a StreamingSTT adapter for live transcription and "
        "a microphone for audio events. Inject via RealtimeVoiceSkill(stt=...)."
    )

    def __init__(self, stt: StreamingSTT | None = None) -> None:
        self._stt: StreamingSTT = stt or StubStreamingSTT()
        self._turn = RealtimeTurn()

    async def handle(self, context: SkillContext) -> str:
        """Run one realtime turn, or report the missing adapter."""
        try:
            transcript = await self._stt.transcribe_stream()
        except AdapterNotConfiguredError as exc:
            return f"realtime: {exc} (turn state: {self._turn.state.value})"
        self._turn.on_partial(transcript)
        self._turn.begin_response()
        return f"realtime: heard '{transcript}' (turn state: {self._turn.state.value})"


SKILLS: list[Skill] = [RealtimeVoiceSkill()]
