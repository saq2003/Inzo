"""Global hotkey registry (conflict detection is real; capture is an adapter).

The registry itself is fully local: combos are normalized
(``Ctrl+Shift+A`` == ``ctrl+shift+a``), duplicates are detected, and the
registry persists in ``data_dir/"hotkeys.db"`` via ``SQLiteKVStore``.

Actually listening for key presses needs OS integration, so the
:class:`GlobalHotkey` Protocol is the plug-in boundary for a real
listener (implemented outside this codebase). Registrations made while
no listener is wired are stored with status ``pending`` and reported
honestly.
"""

from __future__ import annotations

import json
import shlex
from typing import Protocol, cast

from skills.base import Skill, SkillContext, require_data_dir
from skills.desktop.tray_app import NotConfiguredError
from storage.sqlite_store import SQLiteKVStore

_MODIFIERS = {"ctrl", "alt", "shift", "meta", "super", "cmd", "win", "option"}
_DB_NAME = "hotkeys.db"
_STORE_KEY = "registry"


class GlobalHotkey(Protocol):
    """OS global-hotkey listener (implemented outside this codebase)."""

    def register_combo(self, combo: str, action: str) -> bool:
        """Start listening for ``combo``; return True on success."""
        ...

    def unregister_combo(self, combo: str) -> bool:
        """Stop listening for ``combo``; return True on success."""
        ...


class _UnconfiguredHotkeys:
    """Placeholder listener that refuses honestly."""

    def register_combo(self, combo: str, action: str) -> bool:
        raise NotConfiguredError(
            "no GlobalHotkey listener configured: inject one via "
            "HotkeySkill(listener=...) implemented outside this codebase."
        )

    def unregister_combo(self, combo: str) -> bool:
        raise NotConfiguredError("no GlobalHotkey listener configured")


def normalize_combo(combo: str) -> str:
    """Normalize a hotkey combo; raise ValueError if malformed.

    ``Ctrl-Shift-A`` → ``ctrl+shift+a``: modifiers lowercased, deduplicated,
    and sorted; the final part is the key.
    """
    parts = [p.strip().lower() for p in combo.replace("-", "+").split("+")]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        raise ValueError(f"combo needs a modifier + key: {combo!r}")
    *mods, key = parts
    for mod in mods:
        if mod not in _MODIFIERS:
            raise ValueError(f"unknown modifier {mod!r} in {combo!r}")
    if not key or key in _MODIFIERS:
        raise ValueError(f"combo needs a non-modifier key: {combo!r}")
    return "+".join(sorted(set(mods)) + [key])


def _load(store: SQLiteKVStore) -> list[dict[str, str]]:
    raw = store.get(_STORE_KEY)
    if not raw:
        return []
    return cast("list[dict[str, str]]", json.loads(raw))


def _save(store: SQLiteKVStore, items: list[dict[str, str]]) -> None:
    store.put(_STORE_KEY, json.dumps(items))


class HotkeySkill(Skill):
    """Registers/lists global hotkeys with conflict detection."""

    name = "hotkey"
    description = (
        "Registers global hotkeys with normalization and conflict "
        "detection (persisted); OS-level listening needs a plugged-in "
        "GlobalHotkey adapter."
    )
    intents = ("hotkey.register", "hotkey.list")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = False
    adapter_note = (
        "Real key listening needs an OS-specific GlobalHotkey implementation "
        "outside this codebase, injected via HotkeySkill(listener=...). "
        "Registration, normalization, and conflict detection are local."
    )

    def __init__(self, listener: GlobalHotkey | None = None) -> None:
        self._listener: GlobalHotkey = (
            listener if listener is not None else _UnconfiguredHotkeys()
        )

    def _store(self, context: SkillContext) -> SQLiteKVStore:
        return SQLiteKVStore(require_data_dir(context) / _DB_NAME)

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith(("list", "hotkey.list")):
            items = _load(self._store(context))
            if not items:
                return "no hotkeys registered"
            lines = ["registered hotkeys:"]
            for item in items:
                lines.append(
                    f"- {item['combo']} -> {item['action']} [{item['status']}]"
                )
            return "\n".join(lines)
        kv = _kv(text)
        combo_raw = kv.get("combo", "")
        action = kv.get("action", "")
        if not combo_raw or not action:
            return "hotkey: usage: 'register combo=<modifiers+key> action=<description>'"
        try:
            combo = normalize_combo(combo_raw)
        except ValueError as exc:
            return f"hotkey error: {exc}"
        store = self._store(context)
        items = _load(store)
        for item in items:
            if item["combo"] == combo and item["action"] != action:
                return (
                    f"hotkey conflict: {combo} is already registered for "
                    f"'{item['action']}' (status {item['status']})"
                )
            if item["combo"] == combo and item["action"] == action:
                return f"hotkey {combo} is already registered for '{action}'"
        try:
            live = self._listener.register_combo(combo, action)
        except NotConfiguredError:
            live = False
        status = "active" if live else "pending (no listener configured)"
        items.append({"combo": combo, "action": action, "status": status})
        _save(store, items)
        return f"hotkey registered: {combo} -> {action} [{status}]"


def _kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in shlex.split(text):
        if "=" in token:
            key, _, value = token.partition("=")
            out[key.strip().lower()] = value.strip()
    return out


SKILLS: list[Skill] = [HotkeySkill()]
