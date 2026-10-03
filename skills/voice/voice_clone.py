"""Voice clone skill: consent-gated voice enrollment, pluggable synthesis.

Real (deterministic, stdlib): enrollment records require an explicit consent
flag and are stored as a manifest in a SQLite KV store. Synthesis needs a
voice model engine, so it is defined as :class:`VoiceCloneEngine` with a stub
that raises :class:`AdapterNotConfiguredError` instead of fabricating audio.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Protocol, cast

from skills.base import Skill, SkillContext, SkillError, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_DB_NAME = "voice_clones.db"


class AdapterNotConfiguredError(RuntimeError):
    """Raised when a voice-clone engine is required but not configured."""


def _manifest(store: SQLiteKVStore) -> dict[str, dict[str, object]]:
    raw = store.get("voice_clone:manifest")
    if raw is None:
        return {}
    return cast("dict[str, dict[str, object]]", json.loads(raw))


def _save_manifest(store: SQLiteKVStore, manifest: dict[str, dict[str, object]]) -> None:
    store.put("voice_clone:manifest", json.dumps(manifest))


def enroll_voice_clone(store: SQLiteKVStore, voice_id: str, *, consent: bool) -> None:
    """Record a voice-clone enrollment. Consent is mandatory.

    Args:
        store: the voice-clone KV store.
        voice_id: identifier for the enrolled voice.
        consent: explicit consent from the voice owner.

    Raises:
        SkillError: if ``consent`` is False — enrollment is refused.
    """
    if not consent:
        raise SkillError(
            "voice-clone enrollment refused: explicit consent from the voice "
            "owner is required"
        )
    manifest = _manifest(store)
    manifest[voice_id] = {
        "voice_id": voice_id,
        "consent": True,
        "enrolled_at": datetime.now(UTC).isoformat(),
    }
    _save_manifest(store, manifest)


def is_enrolled(store: SQLiteKVStore, voice_id: str) -> bool:
    """Return True when ``voice_id`` has a consent-gated enrollment record."""
    return voice_id in _manifest(store)


class VoiceCloneEngine(Protocol):
    """Plug-in point: voice-cloning model engine.

    A production adapter implements this (e.g. Coqui XTTS, ElevenLabs) and is
    injected into :class:`VoiceCloneSkill`. Until configured, synthesis raises
    instead of fabricating audio.
    """

    def enroll_voice(self, samples: bytes) -> str:
        """Enroll a voice from reference samples; returns a voice id."""
        ...

    def synthesize(self, voice_id: str, text: str) -> bytes:
        """Synthesize speech for ``voice_id``; returns raw PCM bytes."""
        ...


class StubVoiceCloneEngine:
    """Voice-clone engine stub: always reports that it is not configured."""

    def enroll_voice(self, samples: bytes) -> str:
        raise AdapterNotConfiguredError(
            "voice cloning not configured: plug in a VoiceCloneEngine adapter"
        )

    def synthesize(self, voice_id: str, text: str) -> bytes:
        raise AdapterNotConfiguredError(
            "voice cloning not configured: plug in a VoiceCloneEngine adapter"
        )


class VoiceCloneSkill(Skill):
    """Manages consent-gated voice cloning enrollment and synthesis."""

    name = "voice_clone"
    description = "Consent-gated voice cloning with a pluggable synthesis engine."
    intents = ("voice.clone_enroll", "voice.clone_speak")
    required_capabilities = ("skills.execute", "memory.write", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Needs provider/model: a VoiceCloneEngine adapter (e.g. Coqui XTTS) for "
        "enrollment and synthesis. Enrollment is additionally consent-gated. "
        "Inject via VoiceCloneSkill(engine=...)."
    )

    def __init__(self, engine: VoiceCloneEngine | None = None) -> None:
        self._engine: VoiceCloneEngine = engine or StubVoiceCloneEngine()

    async def handle(self, context: SkillContext) -> str:
        """Enroll or synthesize a voice from the message.

        Message protocol: ``enroll: <voice-id> consent=yes`` or
        ``speak: <voice-id> | <text>``.
        """
        data_dir = require_data_dir(context)
        store = SQLiteKVStore(data_dir / _DB_NAME)
        text = context.message.strip()
        lowered = text.lower()
        try:
            if lowered.startswith("enroll:"):
                rest = text.split(":", 1)[1].strip()
                voice_id = rest.split()[0] if rest.split() else ""
                consent = "consent=yes" in lowered.replace(" ", "")
                if not voice_id:
                    return "voice clone: usage is 'enroll: <voice-id> consent=yes'"
                enroll_voice_clone(store, voice_id, consent=consent)
                try:
                    engine_id = self._engine.enroll_voice(b"")
                except AdapterNotConfiguredError as exc:
                    return f"voice clone: {exc}"
                if engine_id and engine_id != voice_id:
                    enroll_voice_clone(store, engine_id, consent=True)
                    return f"voice clone: enrolled '{engine_id}' with consent"
                return f"voice clone: enrolled '{voice_id}' with consent"
            if lowered.startswith("speak:"):
                rest = text.split(":", 1)[1]
                voice_id, _, speech_text = rest.partition("|")
                voice_id, speech_text = voice_id.strip(), speech_text.strip()
                if not voice_id or not speech_text:
                    return "voice clone: usage is 'speak: <voice-id> | <text>'"
                if not is_enrolled(store, voice_id):
                    return (
                        f"voice clone: '{voice_id}' is not enrolled "
                        "(consent-gated enrollment required first)"
                    )
                try:
                    audio = self._engine.synthesize(voice_id, speech_text)
                except AdapterNotConfiguredError as exc:
                    return f"voice clone: {exc}"
                return f"voice clone: synthesized {len(audio)} bytes for '{voice_id}'"
        except SkillError as exc:
            return f"voice clone error: {exc}"
        return "voice clone: use 'enroll: <voice-id> consent=yes' or 'speak: <voice-id> | <text>'"


SKILLS: list[Skill] = [VoiceCloneSkill()]
