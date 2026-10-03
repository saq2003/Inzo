"""Tray/host notification skill (adapter-based, headless-first).

No GUI code lives in this project. The :class:`TrayHost` Protocol is the
plug-in boundary: a real tray host (for example a ``pystray``-based
implementation) is constructed and injected OUTSIDE this codebase via
``TrayAppSkill(host=...)`` — see the skill's ``adapter_note``.

With no host configured, ``show_notification`` falls back headlessly: it
routes through the context's ``NotificationCenter`` when one is wired, and
otherwise returns a plain-text rendering. Nothing is ever faked as a real
OS notification.
"""

from __future__ import annotations

import shlex
from typing import Protocol

from skills.base import Skill, SkillContext


class NotConfiguredError(RuntimeError):
    """Raised when an external desktop adapter is not wired up yet."""


class TrayHost(Protocol):
    """OS tray integration point (implemented outside this codebase)."""

    def show_notification(self, title: str, body: str) -> None:
        """Show a native desktop notification."""
        ...

    def set_tooltip(self, text: str) -> None:
        """Set the tray icon tooltip text."""
        ...

    def quit(self) -> None:
        """Shut the tray host down."""
        ...


class _UnconfiguredTrayHost:
    """Placeholder TrayHost that refuses honestly."""

    def show_notification(self, title: str, body: str) -> None:
        raise NotConfiguredError(
            "no TrayHost configured: inject a real tray host via "
            "TrayAppSkill(host=...) (e.g. a pystray adapter outside this codebase)."
        )

    def set_tooltip(self, text: str) -> None:
        raise NotConfiguredError("no TrayHost configured")

    def quit(self) -> None:
        raise NotConfiguredError("no TrayHost configured")


def _headless_notify(context: SkillContext, title: str, body: str) -> str:
    """Route a notification without a tray host; never fakes delivery."""
    notifier = getattr(context, "notifications", None)
    notify_fn = getattr(notifier, "notify", None) if notifier is not None else None
    if callable(notify_fn):
        notify_fn(title, body)
        return f"notification routed to NotificationCenter (headless): {title}"
    return (
        "[headless tray] no tray host and no NotificationCenter wired — "
        f"notification not delivered, rendered as text: {title}: {body}"
    )


def _parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in shlex.split(text):
        if "=" in token:
            key, _, value = token.partition("=")
            out[key.strip().lower()] = value.strip()
    return out


class TrayAppSkill(Skill):
    """Tray notifications via a pluggable TrayHost; headless fallback."""

    name = "tray_app"
    description = (
        "Shows desktop notifications and manages tray state through a "
        "pluggable TrayHost adapter; falls back to NotificationCenter or "
        "plain text when headless."
    )
    intents = ("tray.show",)
    required_capabilities = ("skills.execute", "notify.send")
    background = True
    local_only = False
    adapter_note = (
        "Plug a real tray host OUTSIDE this codebase (e.g. a pystray-based "
        "class implementing TrayHost) and inject it with "
        "TrayAppSkill(host=...). No GUI code lives in this project; without "
        "a host, notifications degrade to NotificationCenter/plain text."
    )

    def __init__(self, host: TrayHost | None = None) -> None:
        self._host: TrayHost = host if host is not None else _UnconfiguredTrayHost()

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("tooltip"):
            tooltip = text[len("tooltip") :].strip()
            if not tooltip:
                return "tray: usage: 'tooltip <text>'"
            try:
                self._host.set_tooltip(tooltip)
            except NotConfiguredError as exc:
                return f"tray: {exc}"
            return f"tray tooltip set: {tooltip}"
        if lowered == "quit":
            try:
                self._host.quit()
            except NotConfiguredError as exc:
                return f"tray: {exc}"
            return "tray host asked to quit"
        kv = _parse_kv(text)
        title = kv.get("title", "")
        body = kv.get("body", "")
        if not title and not body:
            return (
                "tray: usage: 'notify title=<title> body=<body>' | "
                "'tooltip <text>' | 'quit'"
            )
        try:
            self._host.show_notification(title or "INZO", body)
        except NotConfiguredError:
            return _headless_notify(context, title or "INZO", body)
        return f"notification shown via tray host: {title or 'INZO'}"


SKILLS: list[Skill] = [TrayAppSkill()]
