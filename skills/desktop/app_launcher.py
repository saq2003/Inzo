"""App launcher (adapter-based; NEVER launches from natural language via shell).

Rule 12: this module never uses subprocess, os.system, or any shell
execution. Launching happens ONLY through the :class:`AppLauncher`
Protocol, which is implemented and injected OUTSIDE this codebase via
``AppLauncherSkill(launcher=...)``.

What IS real and local: the alias registry mapping friendly names to app
IDs (``alias add <name> <app_id>``), persisted in ``data_dir/"apps.db"``
via ``SQLiteKVStore``. ``app.launch`` resolves the alias and calls the
adapter; with no adapter configured the launch is refused honestly.
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Protocol, cast

from skills.base import Skill, SkillContext, require_data_dir
from skills.desktop.tray_app import NotConfiguredError
from storage.sqlite_store import SQLiteKVStore

_DB_NAME = "apps.db"
_ALIASES_KEY = "aliases"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AppLauncher(Protocol):
    """OS app-launch integration point (implemented outside this codebase)."""

    def launch(self, app_id: str) -> bool:
        """Launch the app identified by ``app_id``; return True on success."""
        ...


class _UnconfiguredLauncher:
    """Placeholder launcher that refuses honestly (never shells out)."""

    def launch(self, app_id: str) -> bool:
        raise NotConfiguredError(
            "no AppLauncher configured: inject one via "
            "AppLauncherSkill(launcher=...) implemented outside this codebase. "
            "This module never launches apps via subprocess (Rule 12)."
        )


def _load_aliases(store: SQLiteKVStore) -> dict[str, str]:
    raw = store.get(_ALIASES_KEY)
    return cast("dict[str, str]", json.loads(raw)) if raw else {}


def _save_aliases(store: SQLiteKVStore, aliases: dict[str, str]) -> None:
    store.put(_ALIASES_KEY, json.dumps(aliases))


class AppLauncherSkill(Skill):
    """Alias registry + adapter-gated app launching (no subprocess)."""

    name = "app_launcher"
    description = (
        "Keeps a name->app-id alias registry and launches apps only through "
        "a pluggable AppLauncher adapter; never uses subprocess (Rule 12)."
    )
    intents = ("app.alias_add", "app.launch")
    required_capabilities = ("skills.execute", "memory.write")
    background = True
    local_only = False
    adapter_note = (
        "Launching needs an OS-specific AppLauncher implementation outside "
        "this codebase: AppLauncherSkill(launcher=...). The alias registry is "
        "local. Shell execution from natural-language input is forbidden "
        "(Rule 12) — there is no code path that launches via subprocess."
    )

    def __init__(self, launcher: AppLauncher | None = None) -> None:
        self._launcher: AppLauncher = (
            launcher if launcher is not None else _UnconfiguredLauncher()
        )

    def _store(self, context: SkillContext) -> SQLiteKVStore:
        return SQLiteKVStore(require_data_dir(context) / _DB_NAME)

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("alias"):
            return self._alias_add(context, text[len("alias") :].strip())
        if lowered.startswith("app.alias_add"):
            return self._alias_add(context, text[len("app.alias_add") :].strip())
        payload = text
        if lowered.startswith("app.launch"):
            payload = text[len("app.launch") :].strip()
        elif lowered.startswith("launch"):
            payload = text[len("launch") :].strip()
        return self._launch(context, payload)

    def _alias_add(self, context: SkillContext, payload: str) -> str:
        # "alias add <name> <app_id>"
        tokens = shlex.split(payload)
        if len(tokens) == 3 and tokens[0].lower() == "add":
            _, name, app_id = tokens
        elif len(tokens) == 2:
            name, app_id = tokens
        else:
            return "app_launcher: usage: 'alias add <name> <app_id>'"
        if not _NAME_RE.fullmatch(name.lower()):
            return f"app_launcher: invalid alias name: {name!r} (use [a-z0-9_-])"
        if not app_id or len(app_id) > 256:
            return "app_launcher: app_id must be a non-empty string (max 256 chars)"
        store = self._store(context)
        aliases = _load_aliases(store)
        aliases[name.lower()] = app_id
        _save_aliases(store, aliases)
        return f"app_launcher: alias '{name.lower()}' -> '{app_id}' saved"

    def _launch(self, context: SkillContext, payload: str) -> str:
        name = payload.strip().lower()
        if not name:
            return "app_launcher: usage: 'launch <alias-or-app-id>'"
        store = self._store(context)
        app_id = _load_aliases(store).get(name, payload.strip())
        try:
            ok = self._launcher.launch(app_id)
        except NotConfiguredError as exc:
            return f"app_launcher: launch refused — {exc}"
        return (
            f"app_launcher: launched '{app_id}'"
            if ok
            else f"app_launcher: adapter reported failure launching '{app_id}'"
        )


SKILLS: list[Skill] = [AppLauncherSkill()]
