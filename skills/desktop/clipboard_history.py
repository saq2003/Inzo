"""Clipboard history (fully local).

A real in-memory ring buffer (max 100 entries) with ``put`` / ``history`` /
``search`` / ``clear``. Reading and writing the OS clipboard needs platform
integration, so :class:`ClipboardBackend` is the plug-in boundary,
implemented outside this codebase; the bundled stub documents that
integration point and refuses honestly when used.

The ring buffer always works regardless of backend state — history is a
local feature, not a claim about the OS clipboard.
"""

from __future__ import annotations

from collections import deque
from typing import Protocol

from skills.base import Skill, SkillContext
from skills.desktop.tray_app import NotConfiguredError

_MAX_ENTRIES = 100


class ClipboardBackend(Protocol):
    """OS clipboard integration point (implemented outside this codebase)."""

    def read(self) -> str | None:
        """Return current OS clipboard text, or None if empty/unavailable."""
        ...

    def write(self, text: str) -> None:
        """Write ``text`` to the OS clipboard."""
        ...


class _UnconfiguredClipboardBackend:
    """Placeholder backend documenting the OS integration point."""

    def read(self) -> str | None:
        raise NotConfiguredError(
            "no ClipboardBackend configured: implement ClipboardBackend with "
            "an OS API (e.g. pbcopy/AppKit on macOS, xclip on Linux, "
            "win32clipboard on Windows) outside this codebase and inject it "
            "via ClipboardHistorySkill(backend=...)."
        )

    def write(self, text: str) -> None:
        raise NotConfiguredError("no ClipboardBackend configured")


class ClipboardHistorySkill(Skill):
    """In-memory clipboard ring buffer with search."""

    name = "clipboard_history"
    description = (
        "Keeps a local in-memory ring buffer (max 100) of clipboard entries "
        "with put/history/search/clear; OS clipboard access goes through a "
        "pluggable ClipboardBackend."
    )
    intents = ("clipboard.put", "clipboard.history", "clipboard.search")
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    def __init__(self, backend: ClipboardBackend | None = None) -> None:
        self._backend: ClipboardBackend = (
            backend if backend is not None else _UnconfiguredClipboardBackend()
        )
        self._ring: deque[str] = deque(maxlen=_MAX_ENTRIES)

    def put(self, text: str) -> int:
        """Store ``text``; return the new entry count."""
        if not text:
            raise ValueError("cannot store empty clipboard text")
        self._ring.append(text)
        try:
            self._backend.write(text)
        except NotConfiguredError:
            pass  # local history works without an OS backend
        return len(self._ring)

    def history(self, limit: int = 10) -> list[str]:
        """Return the most recent entries, newest first."""
        if limit < 1:
            raise ValueError("limit must be >= 1")
        return list(reversed(self._ring))[:limit]

    def search(self, term: str, limit: int = 10) -> list[str]:
        """Case-insensitive substring search, newest first."""
        lowered = term.lower()
        return [entry for entry in reversed(self._ring) if lowered in entry.lower()][
            :limit
        ]

    def clear(self) -> int:
        """Empty the buffer; return the number of entries removed."""
        removed = len(self._ring)
        self._ring.clear()
        return removed

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        for prefix in ("clipboard.put", "put"):
            if lowered.startswith(prefix):
                payload = text[len(prefix) :].strip()
                if not payload:
                    return "clipboard: usage: 'put <text>'"
                try:
                    count = self.put(payload)
                except ValueError as exc:
                    return f"clipboard error: {exc}"
                return f"clipboard: stored ({count} entr{'y' if count == 1 else 'ies'} in history)"
        for prefix in ("clipboard.history", "history"):
            if lowered == prefix or lowered.startswith(prefix + " "):
                rest = text[len(prefix) :].strip()
                try:
                    limit = int(rest) if rest else 10
                    entries = self.history(limit)
                except ValueError as exc:
                    return f"clipboard error: {exc}"
                if not entries:
                    return "clipboard history is empty"
                lines = ["clipboard history (newest first):"]
                lines.extend(f"{i + 1}. {entry[:120]}" for i, entry in enumerate(entries))
                return "\n".join(lines)
        for prefix in ("clipboard.search", "search"):
            if lowered.startswith(prefix):
                term = text[len(prefix) :].strip()
                if not term:
                    return "clipboard: usage: 'search <term>'"
                hits = self.search(term)
                if not hits:
                    return f"clipboard: no entries matching {term!r}"
                lines = [f"clipboard matches for {term!r}:"]
                lines.extend(f"{i + 1}. {entry[:120]}" for i, entry in enumerate(hits))
                return "\n".join(lines)
        if lowered in ("clear", "clipboard.clear"):
            removed = self.clear()
            noun = "entry" if removed == 1 else "entries"
            return f"clipboard: cleared {removed} {noun}"
        return (
            "clipboard: try 'put <text>', 'history [n]', 'search <term>', or 'clear'."
        )


SKILLS: list[Skill] = [ClipboardHistorySkill()]
