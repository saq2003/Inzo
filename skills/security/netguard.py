"""Shared network-guard format for INZO security skills.

This module contains NO skills and NO ``SKILLS`` list. It defines the
on-disk format of ``netguard.json`` and the tiny ``NetworkGuard`` helper
that skill daemons consult before any network access:

    {"mode": "normal" | "local_only", "allow": {skill_name: [host, ...]}}

Rules:
  * mode == "local_only"  -> every network call is blocked for every skill.
  * otherwise, a skill's ``allow`` list acts as a host allowlist. If the
    list is missing or empty for a skill, the call is permitted.
  * ``check`` raises ``GuardBlocked`` so callers fail closed.

Pure stdlib (json + urllib.parse); no I/O beyond one small file read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from urllib.parse import urlparse


class GuardBlocked(Exception):
    """Raised when the network guard blocks a call. Callers fail closed."""


class NetworkGuard:
    """Tiny reader for ``data_dir/netguard.json``.

    ``is_blocked`` returns True when mode is "local_only" or when the
    skill has a non-empty host allowlist that does not contain the URL's
    host. ``check`` raises ``GuardBlocked`` instead of returning False.
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "netguard.json"

    def _config(self) -> dict[str, object]:
        """Read and validate the config file; fall back to permissive normal."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return {"mode": "normal", "allow": {}}
        try:
            data = cast("dict[str, object]", json.loads(raw))
        except ValueError:
            return {"mode": "normal", "allow": {}}
        if not isinstance(data, dict):
            return {"mode": "normal", "allow": {}}
        return data

    def _allowlist(self) -> dict[str, object]:
        allow = self._config().get("allow")
        return allow if isinstance(allow, dict) else {}

    def is_blocked(self, skill_name: str, url: str) -> bool:
        """True when the call must be blocked (fail closed)."""
        mode = self._config().get("mode")
        if mode == "local_only":
            return True
        hosts = self._allowlist().get(skill_name)
        if not hosts:  # missing or empty allowlist -> permitted
            return False
        if not isinstance(hosts, list):
            return False
        host = (urlparse(url).hostname or "").lower()
        allowed = [str(h).lower() for h in hosts]
        return host not in allowed

    def check(self, skill_name: str, url: str) -> None:
        """Raise ``GuardBlocked`` if the call is not permitted."""
        if self.is_blocked(skill_name, url):
            raise GuardBlocked(f"network blocked for {skill_name!r}: {url}")
