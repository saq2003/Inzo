"""Notification center: durable inbox plus desktop/webhook fan-out.

Every notification is persisted to a SQLite-backed inbox first. Optional
``desktop`` (plyer) and ``webhook`` (urllib POST) channels are best-effort:
failures are logged and never raised to the caller.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.logging_config import get_logger
from storage.sqlite_store import SQLiteDocumentStore, SQLiteKVStore

logger = get_logger(__name__)

_WEBHOOK_TIMEOUT_S = 5.0
_WEBHOOK_MAX_RETRIES = 2


def _post_json_sync(url: str, payload: dict[str, Any]) -> None:
    """POST ``payload`` as JSON; raises on any failure (sync, thread-safe)."""
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"refusing webhook with non-http(s) scheme: {scheme!r}")
    body = json.dumps(payload).encode("utf-8")
    # Scheme is validated above; only http(s) webhooks are ever requested.
    request = urllib.request.Request(  # noqa: S310
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(  # noqa: S310 - scheme validated above
                request, timeout=_WEBHOOK_TIMEOUT_S
            ) as response:
                status = response.status
            if status >= 400:
                raise OSError(f"webhook returned HTTP {status}")
            return
        except Exception as exc:
            attempt += 1
            if attempt > _WEBHOOK_MAX_RETRIES:
                raise
            backoff = min(2.0**attempt, 8.0)
            logger.warning(
                "webhook attempt failed, retrying",
                extra={"attempt": attempt, "backoff_s": backoff, "error": str(exc)},
            )
            time.sleep(backoff)


class NotificationCenter:
    """Stores notifications in a SQLite inbox and fans out to channels."""

    def __init__(self, data_dir: Path, webhook_url: str | None = None) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self._data_dir = data_dir
        self._webhook_url = webhook_url
        self._store = SQLiteDocumentStore(data_dir / "notifications.db")
        self._read_flags = SQLiteKVStore(data_dir / "notifications_read.db")

    async def notify(
        self,
        title: str,
        body: str,
        *,
        channels: tuple[str, ...] = ("inbox",),
    ) -> dict[str, Any]:
        """Persist to the inbox and fan out to ``channels``. Never raises."""
        created = datetime.now(UTC).isoformat()
        record: dict[str, Any] = {
            "title": title,
            "body": body,
            "channel": list(channels),
            "created": created,
            "read": False,
        }
        try:
            notification_id = self._store.add(record)
        except Exception:
            logger.exception("failed to persist notification to inbox")
            notification_id = "unsaved"

        for channel in channels:
            try:
                if channel == "inbox":
                    continue  # already persisted above
                if channel == "desktop":
                    self._send_desktop(title, body)
                elif channel == "webhook":
                    await self._send_webhook(title, body, created)
                else:
                    logger.warning(
                        "unknown notification channel",
                        extra={"channel": channel},
                    )
            except Exception:
                logger.exception(
                    "notification channel failed", extra={"channel": channel}
                )

        return {
            "id": notification_id,
            "title": title,
            "body": body,
            "channel": list(channels),
            "created": created,
        }

    def _send_desktop(self, title: str, body: str) -> None:
        """Best-effort desktop popup via plyer; falls back to a log line."""
        try:
            from plyer import notification as plyer_notification
        except ImportError:
            logger.info(
                "plyer not installed; desktop notification logged only",
                extra={"title": title},
            )
            return
        try:
            plyer_notification.notify(title=title, message=body, app_name="INZO")
        except Exception:
            logger.exception("desktop notification failed", extra={"title": title})

    async def _send_webhook(self, title: str, body: str, created: str) -> None:
        if not self._webhook_url:
            logger.info("no webhook_url configured; skipping webhook channel")
            return
        payload = {"title": title, "body": body, "created": created}
        await asyncio.to_thread(_post_json_sync, self._webhook_url, payload)
        logger.info("webhook notification sent")

    def _is_read(self, notification_id: str) -> bool:
        return self._read_flags.get(notification_id) is not None

    def inbox_list(
        self, limit: int = 50, unread_only: bool = False
    ) -> list[dict[str, Any]]:
        """Return newest-first inbox entries, each with an ``id`` key."""
        entries: list[dict[str, Any]] = []
        for doc in self._store.search("", limit=10**6):
            entry = dict(doc)
            entry["read"] = self._is_read(str(entry.get("id", "")))
            if unread_only and entry["read"]:
                continue
            entries.append(entry)
            if len(entries) >= max(limit, 0):
                break
        return entries

    def mark_read(self, notification_id: str) -> bool:
        """Mark an inbox entry read; False when the id does not exist."""
        if self._store.get(notification_id) is None:
            return False
        self._read_flags.put(notification_id, "true")
        return True
