"""WhatsApp inbound webhook handling with a provider adapter contract.

Inbound: normalizes Twilio-style and generic webhook JSON payloads to
``{sender, text, timestamp, message_id}`` and dedupes by message id in
``data_dir/"outbox.db"``. Outbound: goes through a ``WhatsAppProvider``
Protocol — with no provider plugged in, sends raise ``SkillError``.
The skill NEVER fake-sends.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from skills.base import Skill, SkillContext, SkillError, require_data_dir
from storage.sqlite_store import SQLiteKVStore


class WhatsAppProvider(Protocol):
    """Plug-in point for a real WhatsApp Business / Twilio sender.

    Implementations must call the provider's HTTPS API (Twilio Messages
    or the WhatsApp Cloud API) with credentials from the Secure Vault.
    Attach with ``WhatsAppBotSkill(provider=...)``.
    """

    def send_message(self, to: str, text: str) -> str:
        """Send a WhatsApp text message; return the provider's message id."""
        ...


class UnconfiguredWhatsAppProvider:
    """Ships with the skill; always fails honestly instead of fake-sending."""

    def send_message(self, to: str, text: str) -> str:
        raise SkillError(
            "whatsapp provider not configured: plug a WhatsAppProvider "
            "(Twilio / WhatsApp Business API) into WhatsAppBotSkill to send"
        )


def _as_str(value: Any) -> str:
    """Coerce a payload field to text."""
    return "" if value is None else str(value)


def normalize_inbound(payload: dict[str, Any]) -> dict[str, str]:
    """Normalize a Twilio-style or generic webhook payload to a common shape.

    Always returns string values for ``sender``, ``text``, ``timestamp``
    and ``message_id`` (missing fields become "" except ``timestamp``,
    which defaults to now in UTC).
    """
    sender = _as_str(payload.get("From") or payload.get("sender") or payload.get("from"))
    sender = sender.removeprefix("whatsapp:")
    text = _as_str(
        payload.get("Body") or payload.get("text") or payload.get("message") or payload.get("body")
    )
    timestamp = _as_str(payload.get("timestamp") or payload.get("Timestamp"))
    if not timestamp:
        timestamp = datetime.now(UTC).isoformat()
    message_id = _as_str(payload.get("MessageSid") or payload.get("message_id") or payload.get("id"))
    return {"sender": sender, "text": text, "timestamp": timestamp, "message_id": message_id}


class WhatsAppBotSkill(Skill):
    """Normalizes WhatsApp inbound webhooks; outbound needs a real provider."""

    name = "whatsapp_bot"
    description = (
        "Normalizes WhatsApp inbound webhooks (Twilio-style or generic) with "
        "message-id dedupe. Outbound delivery needs a WhatsAppProvider and "
        "is never faked."
    )
    intents = ("whatsapp.inbound",)
    required_capabilities = ("skills.execute", "memory.write", "network.fetch")
    background = True
    local_only = False
    adapter_note = (
        "Outbound delivery needs a WhatsAppProvider (Twilio or the WhatsApp "
        "Business Cloud API) attached via WhatsAppBotSkill(provider=...), with "
        "credentials from the Secure Vault. Without one, sends raise "
        "SkillError; nothing is ever fake-sent."
    )

    def __init__(self, provider: WhatsAppProvider | None = None) -> None:
        self._provider: WhatsAppProvider = provider or UnconfiguredWhatsAppProvider()

    def set_provider(self, provider: WhatsAppProvider) -> None:
        """Attach a real WhatsApp provider implementation."""
        self._provider = provider

    def send_outbound(self, to: str, text: str) -> str:
        """Send via the plugged provider; raises SkillError when unconfigured."""
        return self._provider.send_message(to, text)

    async def _remember(self, context: SkillContext, sender: str, text: str) -> None:
        if context.memory is None:
            return
        await context.memory.remember(
            "whatsapp",
            f"inbound from {sender or 'unknown'}: {text[:200]}",
            durable=False,
            kind="whatsapp_inbound",
        )

    async def handle(self, context: SkillContext) -> str:
        message = context.message.strip()
        if not message.lower().startswith("inbound:"):
            return (
                "whatsapp_bot: send 'inbound:<json webhook payload>' to normalize "
                "an inbound WhatsApp message (Twilio or generic shape)"
            )
        raw = message[len("inbound:") :].strip()
        try:
            payload = cast("dict[str, Any]", json.loads(raw))
        except json.JSONDecodeError as exc:
            raise SkillError(f"invalid inbound JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise SkillError("inbound payload must be a JSON object")
        normalized = normalize_inbound(payload)

        seen = SQLiteKVStore(require_data_dir(context) / "outbox.db")
        dedupe_id = normalized["message_id"] or f"{normalized['sender']}:{normalized['timestamp']}"
        if seen.get(f"seen:{dedupe_id}") is not None:
            return (
                f"duplicate inbound from {normalized['sender'] or 'unknown'} ignored "
                f"(message_id={normalized['message_id'] or 'n/a'})"
            )
        seen.put(f"seen:{dedupe_id}", normalized["timestamp"])
        await self._remember(context, normalized["sender"], normalized["text"])

        text = normalized["text"]
        preview = text[:120] + ("…" if len(text) > 120 else "")
        return (
            f"inbound whatsapp from {normalized['sender'] or 'unknown'} "
            f"at {normalized['timestamp']}: {preview or '(no text)'}"
        )


SKILLS: list[Skill] = [WhatsAppBotSkill()]
