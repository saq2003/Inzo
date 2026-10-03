"""Voice lock skill (hardware-gated voice + real local PIN fallback).

The ``VoiceBiometric`` Protocol is the plug-in point for real voice
biometrics; the bundled ``StubVoice`` raises ``NotConfigured``. The PIN
fallback is fully real and local: the PIN is never stored in plaintext —
it is kept as PBKDF2-HMAC-SHA256 (200,000 iterations, 16-byte ``secrets``
salt) in ``data_dir/"pinlock.db"``, verified with ``hmac.compare_digest``,
and 5 consecutive failures trigger a 10-minute lockout.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Protocol, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

PIN_KEY = "pinlock:verifier"
FAIL_KEY = "pinlock:failures"
ITERATIONS = 200_000
SALT_BYTES = 16
MAX_FAILURES = 5
LOCKOUT_SECONDS = 600.0


class NotConfigured(Exception):
    """Raised by stub adapters when no real hardware backend is plugged in."""


class VoiceBiometric(Protocol):
    """Plug-in point: real voice-biometric verification.

    Attach with ``VoiceLockSkill.set_voice``.
    """

    def verify(self, sample: bytes) -> bool:
        """Return True when the voice sample matches the enrolled user."""
        ...


class StubVoice:
    """Ships with the skill; always fails honestly."""

    def verify(self, sample: bytes) -> bool:
        raise NotConfigured(
            "no voice biometric configured — plug a VoiceBiometric "
            "implementation via VoiceLockSkill.set_voice, or use the PIN fallback"
        )


def _derive_pin_hash(pin: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 with 200k iterations."""
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, ITERATIONS)


class VoiceLockSkill(Skill):
    """Voice/PIN lock with hashed PIN storage and failure lockout."""

    name = "voice_lock"
    description = (
        "Locks sensitive actions behind voice biometrics with a real local "
        "PIN fallback: PBKDF2-hashed PIN, constant-time verification, and "
        "a 10-minute lockout after 5 failed attempts."
    )
    intents = ("lock.set_pin", "lock.unlock", "lock.status")
    required_capabilities = ("skills.execute", "memory.write")
    background = True
    local_only = False
    adapter_note = (
        "Voice verification needs real biometric hardware/software. "
        "Implement the VoiceBiometric Protocol (verify) and attach via "
        "VoiceLockSkill.set_voice; the bundled StubVoice raises "
        "NotConfigured. The PIN fallback is fully local and real."
    )

    def __init__(self) -> None:
        self._voice: VoiceBiometric = StubVoice()

    def set_voice(self, voice: VoiceBiometric) -> None:
        """Attach a real voice-biometric implementation."""
        self._voice = voice

    def _store(self, context: SkillContext) -> SQLiteKVStore:
        return SQLiteKVStore(require_data_dir(context) / "pinlock.db")

    # -- PIN storage ------------------------------------------------------
    def _pin_set(self, context: SkillContext) -> bool:
        return self._store(context).get(PIN_KEY) is not None

    def set_pin(self, context: SkillContext, pin: str) -> str:
        """Hash and store a new PIN (never stores plaintext)."""
        if len(pin) < 4:
            return "PIN must be at least 4 characters"
        salt = secrets.token_bytes(SALT_BYTES)
        digest = _derive_pin_hash(pin, salt)
        verifier = json.dumps({"salt": salt.hex(), "hash": digest.hex()})
        store = self._store(context)
        store.put(PIN_KEY, verifier)
        store.delete(FAIL_KEY)
        return "PIN set (stored as PBKDF2-HMAC-SHA256, 200k iterations)"

    def _verify_pin(self, context: SkillContext, pin: str) -> bool:
        raw = self._store(context).get(PIN_KEY)
        if raw is None:
            return False
        verifier = cast("dict[str, str]", json.loads(raw))
        salt = bytes.fromhex(verifier["salt"])
        expected = bytes.fromhex(verifier["hash"])
        return hmac.compare_digest(_derive_pin_hash(pin, salt), expected)

    # -- lockout -----------------------------------------------------------
    def _failures(self, context: SkillContext) -> dict[str, float]:
        raw = self._store(context).get(FAIL_KEY)
        if not raw:
            return {"count": 0.0, "locked_until": 0.0}
        data = cast("dict[str, float]", json.loads(raw))
        return {
            "count": float(data.get("count", 0.0)),
            "locked_until": float(data.get("locked_until", 0.0)),
        }

    def _record_failure(self, context: SkillContext) -> None:
        info = self._failures(context)
        self._store(context).put(
            FAIL_KEY,
            json.dumps({"count": info["count"] + 1.0, "locked_until": info["locked_until"]}),
        )

    def _record_lockout(self, context: SkillContext) -> None:
        self._store(context).put(
            FAIL_KEY,
            json.dumps(
                {"count": float(MAX_FAILURES), "locked_until": time.time() + LOCKOUT_SECONDS}
            ),
        )

    def _clear_failures(self, context: SkillContext) -> None:
        self._store(context).delete(FAIL_KEY)

    def _is_locked_out(self, context: SkillContext) -> float:
        """Remaining lockout seconds (0 when not locked out)."""
        remaining = self._failures(context)["locked_until"] - time.time()
        return max(0.0, remaining)

    # -- handling ----------------------------------------------------------
    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lower = text.lower()

        if lower.startswith("set pin"):
            pin = text[len("set pin") :].strip()
            return self.set_pin(context, pin)

        if lower == "status":
            locked = self._is_locked_out(context)
            if locked > 0:
                return f"locked out: try again in {locked:.0f}s"
            return (
                f"PIN: {'set' if self._pin_set(context) else 'not set'}; "
                f"voice: {'configured' if not isinstance(self._voice, StubVoice) else 'NOT configured'}; "
                f"failures: {int(self._failures(context)['count'])}"
            )

        if lower.startswith("unlock"):
            remaining = self._is_locked_out(context)
            if remaining > 0:
                return f"locked out after failed attempts: try again in {remaining:.0f}s"
            credential = text[len("unlock") :].strip()
            if not credential:
                return "usage: unlock <pin> (voice unlock needs a configured adapter)"
            if not self._pin_set(context):
                return "no PIN set — 'set pin <pin>' first"
            if self._verify_pin(context, credential):
                self._clear_failures(context)
                return "unlocked"
            self._record_failure(context)
            if self._failures(context)["count"] >= MAX_FAILURES:
                self._record_lockout(context)
                return "wrong PIN — locked out for 10 minutes"
            attempts_left = MAX_FAILURES - int(self._failures(context)["count"])
            return f"wrong PIN — {attempts_left} attempt(s) left before lockout"

        if lower.startswith("voice"):
            try:
                ok = self._voice.verify(b"")
            except NotConfigured as exc:
                return f"not configured: {exc}"
            return "voice verification passed" if ok else "voice verification failed"

        return (
            "lock: 'set pin <pin>', 'unlock <pin>', 'voice' (needs adapter), 'status'. "
            f"voice adapter: {'configured' if not isinstance(self._voice, StubVoice) else 'NOT configured'}"
        )


SKILLS: list[Skill] = [VoiceLockSkill()]
