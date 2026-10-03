"""Comms skill tests (offline, deterministic; no provider is ever touched)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from skills.base import Skill, SkillContext
from skills.comms.whatsapp_bot import normalize_inbound
from skills.discovery import build_skill_registry


def _ctx(tmp_path: Path, message: str) -> SkillContext:
    """Bare skill context over an isolated data dir."""
    return SkillContext(
        actor="test", message=message, memory=None, tools=None, data_dir=tmp_path
    )


def _skill(name: str) -> Skill:
    """Fetch a skill from a fresh registry."""
    return build_skill_registry().get(name)


def test_whatsapp_normalize_inbound_twilio_shape() -> None:
    """Twilio-style payloads normalize to sender/text/timestamp/message_id."""
    payload: dict[str, Any] = {
        "From": "whatsapp:+919876543210",
        "Body": "namaste bhai",
        "MessageSid": "SM123",
        "timestamp": "2026-10-03T10:00:00+00:00",
    }
    normalized = normalize_inbound(payload)
    assert normalized["sender"] == "+919876543210"
    assert normalized["text"] == "namaste bhai"
    assert normalized["message_id"] == "SM123"
    assert normalized["timestamp"] == "2026-10-03T10:00:00+00:00"


def test_whatsapp_normalize_inbound_generic_shape() -> None:
    """Generic webhook payloads normalize with the same keys."""
    payload: dict[str, Any] = {"sender": "+91111", "text": "hi"}
    normalized = normalize_inbound(payload)
    assert normalized["sender"] == "+91111"
    assert normalized["text"] == "hi"
    assert normalized["message_id"] == ""
    assert normalized["timestamp"]  # defaults to now


def test_whatsapp_bot_handle_inbound(tmp_path: Path) -> None:
    """The skill handle() normalizes an inbound: payload and never fakes a send."""
    payload = json.dumps({"From": "whatsapp:+919876543210", "Body": "hello"})
    result = asyncio.run(
        _skill("whatsapp_bot").handle(_ctx(tmp_path, f"inbound:{payload}"))
    )
    assert "+919876543210" in result
    assert "sent" not in result.lower() or "not sent" in result.lower()


def test_send_message_queues_never_claims_sent(tmp_path: Path) -> None:
    """'send' queues the message; 'outbox' shows it as pending, not sent."""
    skill = _skill("send_message")
    queued = asyncio.run(skill.handle(_ctx(tmp_path, "send +919876543210 hello there")))
    assert "queued" in queued

    outbox = asyncio.run(skill.handle(_ctx(tmp_path, "outbox")))
    assert "outbox" in outbox
    assert "hello there" in outbox
    assert "pending" in outbox
    assert "sent" not in outbox.replace("provider", "")


def test_translator_hello_to_hindi(tmp_path: Path) -> None:
    """'translate hello' returns the Hindi dictionary word."""
    result = asyncio.run(_skill("translator").handle(_ctx(tmp_path, "translate hello")))
    assert "नमस्ते" in result


def test_followup_add_then_list(tmp_path: Path) -> None:
    """A follow-up added by NL shows up in 'list'."""
    skill = _skill("followup_tracker")
    added = asyncio.run(
        skill.handle(
            _ctx(tmp_path, "follow up with Ramesh about the invoice in 3 days")
        )
    )
    assert "Ramesh" in added

    listed = asyncio.run(skill.handle(_ctx(tmp_path, "list")))
    assert "Ramesh" in listed
    assert "invoice" in listed
