"""Durable message outbox: enqueue now, deliver through a plugged sender.

``send <to> <text>`` only queues — it never claims delivery. ``outbox``
lists queued items with attempt counts; ``flush`` attempts delivery via
the ``SenderProtocol`` adapter and marks each item sent/failed honestly.
With no sender configured, flush requeues with a clear not-configured
state instead of fake-sending.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Protocol

from skills.base import Skill, SkillContext, SkillError, require_data_dir

_MAX_ATTEMPTS = 3


class SenderProtocol(Protocol):
    """Plug-in point for a real message sender (WhatsApp/Twilio/SMS).

    Attach with ``SendMessageSkill(sender=...)``. Implementations call
    the provider's HTTPS API with credentials from the Secure Vault.
    """

    def send(self, to: str, text: str) -> str:
        """Deliver the message; return the provider message id or raise."""
        ...


class UnconfiguredSender:
    """Ships with the skill; always fails honestly instead of fake-sending."""

    def send(self, to: str, text: str) -> str:
        raise SkillError(
            "no sender configured: plug a SenderProtocol into "
            "SendMessageSkill to deliver queued messages"
        )


@dataclass
class OutboxItem:
    """One queued message."""

    id: int
    recipient: str
    body: str
    status: str
    attempts: int
    next_retry_ts: float
    provider_msg_id: str | None
    last_error: str | None


def _row_to_item(row: tuple[Any, ...]) -> OutboxItem:
    return OutboxItem(
        id=int(row[0]),
        recipient=str(row[1]),
        body=str(row[2]),
        status=str(row[3]),
        attempts=int(row[4]),
        next_retry_ts=float(row[5]),
        provider_msg_id=str(row[6]) if row[6] is not None else None,
        last_error=str(row[7]) if row[7] is not None else None,
    )


class OutboxStore:
    """SQLite outbox with statuses, attempt counts and backoff scheduling."""

    def __init__(self, path: object) -> None:
        self._path = str(path)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS outbox ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "recipient TEXT NOT NULL, body TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'pending', "
                "attempts INTEGER NOT NULL DEFAULT 0, "
                "next_retry_ts REAL NOT NULL DEFAULT 0, "
                "created_ts REAL NOT NULL, "
                "provider_msg_id TEXT, last_error TEXT)"
            )

    def enqueue(self, recipient: str, body: str) -> int:
        """Queue a message; returns its outbox id. Never claims delivery."""
        with sqlite3.connect(self._path) as conn:
            cur = conn.execute(
                "INSERT INTO outbox (recipient, body, status, created_ts) "
                "VALUES (?, ?, 'pending', ?)",
                (recipient, body, time.time()),
            )
            return int(cur.lastrowid or 0)

    def list_all(self, limit: int = 50) -> list[OutboxItem]:
        """Newest-first outbox entries (pending, retrying, sent, failed)."""
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT id, recipient, body, status, attempts, next_retry_ts, "
                "provider_msg_id, last_error FROM outbox "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_item(tuple(row)) for row in rows]

    def due(self, now: float) -> list[OutboxItem]:
        """Items ready for a delivery attempt."""
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT id, recipient, body, status, attempts, next_retry_ts, "
                "provider_msg_id, last_error FROM outbox "
                "WHERE status IN ('pending', 'retry') AND next_retry_ts <= ? "
                "ORDER BY id ASC",
                (now,),
            ).fetchall()
        return [_row_to_item(tuple(row)) for row in rows]

    def mark_sent(self, item_id: int, provider_msg_id: str) -> None:
        """Record an honest, provider-confirmed delivery."""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "UPDATE outbox SET status='sent', provider_msg_id=?, last_error=NULL "
                "WHERE id=?",
                (provider_msg_id, item_id),
            )

    def mark_retry(self, item_id: int, error: str, attempts: int, next_retry_ts: float) -> None:
        """Requeue with backoff after a failed attempt."""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "UPDATE outbox SET status='retry', attempts=?, next_retry_ts=?, "
                "last_error=? WHERE id=?",
                (attempts, next_retry_ts, error, item_id),
            )

    def mark_failed(self, item_id: int, error: str) -> None:
        """Give up after max attempts; the failure stays visible."""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "UPDATE outbox SET status='failed', last_error=? WHERE id=?",
                (error, item_id),
            )


def _backoff_delay_s(attempts: int) -> float:
    return min(60.0 * (2.0**attempts), 3600.0)


class SendMessageSkill(Skill):
    """Durable outbox queue with honest, adapter-gated delivery."""

    name = "send_message"
    description = (
        "Queues outbound messages durably ('send <to> <text>'), lists the "
        "outbox, and flushes it through a plugged sender. Delivery is only "
        "ever claimed when the provider confirms it."
    )
    intents = ("message.send", "message.outbox", "message.flush")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "network.fetch")
    background = True
    local_only = False
    adapter_note = (
        "Delivery needs a SenderProtocol (Twilio / WhatsApp Business API / "
        "SMS gateway) attached via SendMessageSkill(sender=...), with "
        "credentials from the Secure Vault. Without one, messages stay "
        "queued and flush reports not-configured; nothing is fake-sent."
    )

    def __init__(self, sender: SenderProtocol | None = None) -> None:
        self._sender: SenderProtocol = sender or UnconfiguredSender()

    def set_sender(self, sender: SenderProtocol) -> None:
        """Attach a real sender implementation."""
        self._sender = sender

    def _store(self, context: SkillContext) -> OutboxStore:
        return OutboxStore(require_data_dir(context) / "outbox.db")

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        low = text.lower()
        if low.startswith("send ") or low == "send":
            return self._cmd_send(context, text)
        if low == "outbox" or low.startswith("outbox "):
            return self._cmd_outbox(context)
        if low == "flush":
            return self._cmd_flush(context)
        return (
            "send_message usage: 'send <recipient> <text>' to queue, "
            "'outbox' to list queued, 'flush' to attempt delivery"
        )

    def _cmd_send(self, context: SkillContext, text: str) -> str:
        parts = text.split(None, 2)
        if len(parts) < 3 or not parts[2].strip():
            return "usage: send <recipient> <message text>"
        recipient, body = parts[1], parts[2].strip()
        item_id = self._store(context).enqueue(recipient, body)
        if isinstance(self._sender, UnconfiguredSender):
            return (
                f"queued message #{item_id} to {recipient} — held in outbox "
                "(no sender configured; nothing was delivered)"
            )
        return f"queued message #{item_id} to {recipient} — run 'flush' to deliver"

    def _cmd_outbox(self, context: SkillContext) -> str:
        items = self._store(context).list_all()
        if not items:
            return "outbox is empty"
        lines = []
        for item in items:
            preview = item.body[:60] + ("…" if len(item.body) > 60 else "")
            extra = ""
            if item.status == "sent":
                extra = f" provider_id={item.provider_msg_id or 'n/a'}"
            elif item.last_error:
                extra = f" error={item.last_error[:80]}"
            lines.append(
                f"#{item.id} to {item.recipient}: {item.status} "
                f"(attempts={item.attempts}){extra} — {preview}"
            )
        return "outbox:\n" + "\n".join(lines)

    def _cmd_flush(self, context: SkillContext) -> str:
        store = self._store(context)
        now = time.time()
        items = store.due(now)
        if not items:
            return "flush: nothing due for delivery"
        sent, failed, retried = 0, 0, 0
        for item in items:
            try:
                provider_id = self._sender.send(item.recipient, item.body)
            except Exception as exc:  # noqa: BLE001 — provider errors requeue, never crash flush
                attempts = item.attempts + 1
                if attempts >= _MAX_ATTEMPTS:
                    store.mark_failed(item.id, str(exc))
                    failed += 1
                else:
                    store.mark_retry(item.id, str(exc), attempts, now + _backoff_delay_s(attempts))
                    retried += 1
            else:
                store.mark_sent(item.id, provider_id)
                sent += 1
        return f"flush: delivered {sent}, failed {failed}, requeued {retried}"


SKILLS: list[Skill] = [SendMessageSkill()]
