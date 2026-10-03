"""Local-only network mode skill (fully local, real guard control).

Reads and writes ``data_dir/"netguard.json"`` — the same file the
``NetworkGuard`` helper (``skills/security/netguard.py``) reads before
any network call. ``on`` switches the whole daemon to local_only mode
(all network blocked for all skills); ``off`` restores normal mode;
``status`` reports the current mode. Existing host allowlists are
preserved across mode changes.
"""

from __future__ import annotations

import json
from typing import cast

from skills.base import Skill, SkillContext, require_data_dir
from skills.security.netguard import NetworkGuard

MODES = ("normal", "local_only")


class LocalOnlyModeSkill(Skill):
    """Gets/sets the network guard mode: normal or local-only."""

    name = "local_only_mode"
    description = (
        "Controls the network guard: 'on' blocks ALL network access for "
        "ALL skills (local_only mode); 'off' restores normal mode; 'status' "
        "reports the current mode."
    )
    intents = ("netmode.set", "netmode.status")
    required_capabilities = ("skills.execute", "memory.write")
    background = True
    local_only = True

    def _read_config(self, context: SkillContext) -> dict[str, object]:
        path = require_data_dir(context) / "netguard.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return {"mode": "normal", "allow": {}}
        try:
            data = cast("dict[str, object]", json.loads(raw))
        except ValueError:
            return {"mode": "normal", "allow": {}}
        if not isinstance(data, dict):
            return {"mode": "normal", "allow": {}}
        return data

    def _write_mode(self, context: SkillContext, mode: str) -> None:
        config = self._read_config(context)
        config["mode"] = mode
        if not isinstance(config.get("allow"), dict):
            config["allow"] = {}
        path = require_data_dir(context) / "netguard.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip().lower()

        if text in ("on", "enable", "set on"):
            self._write_mode(context, "local_only")
            return "network guard: LOCAL_ONLY — all network blocked for all skills"
        if text in ("off", "disable", "set off"):
            self._write_mode(context, "normal")
            return "network guard: normal — per-skill host allowlists apply"

        mode = self._read_config(context).get("mode", "normal")
        # Demonstrate the guard is wired: a localhost probe would be blocked.
        guard = NetworkGuard(require_data_dir(context))
        blocked = guard.is_blocked("any_skill", "https://example.com")
        return (
            f"network guard mode: {mode}\n"
            f"probe https://example.com would be {'BLOCKED' if blocked else 'allowed'}"
        )


SKILLS: list[Skill] = [LocalOnlyModeSkill()]
