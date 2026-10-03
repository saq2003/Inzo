"""Privacy firewall: per-skill network allowlist enforcement.

Reads ``data_dir/"netguard.json"`` directly (shared format with the
security netguard: ``{"mode": ..., "allow": {skill: [hosts]}}`` — read
here as plain JSON, no import of other skill groups).
:func:`guarded_fetch` blocks by raising :class:`FirewallBlocked` when
``mode == "local_only"``, or when the skill has a non-empty allow-list
and the URL's host is not on it (exact or subdomain match). Allowed
fetches go through ``http.client`` with a timeout (no ``urllib``
``urlopen``, one redirect hop, re-validated against the policy).
"""

from __future__ import annotations

import http.client
import json
import ssl
import urllib.parse
from pathlib import Path
from typing import Any, cast

from skills.base import Skill, SkillContext, require_data_dir

_POLICY_FILE = "netguard.json"
_DEFAULT_POLICY: dict[str, Any] = {"mode": "open", "allow": {}}
_MAX_BODY = 8 * 1024 * 1024


class FirewallBlocked(Exception):
    """Raised when the privacy firewall blocks a network fetch."""


def _load_policy(data_dir: Path) -> dict[str, Any]:
    """Load netguard.json; tolerate missing/corrupt files (default: open)."""
    path = data_dir / _POLICY_FILE
    if not path.exists():
        return {"mode": "open", "allow": {}}
    try:
        policy = cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"mode": "open", "allow": {}}
    if not isinstance(policy, dict):
        return {"mode": "open", "allow": {}}
    return policy


def _save_policy(data_dir: Path, policy: dict[str, Any]) -> None:
    (data_dir / _POLICY_FILE).write_text(json.dumps(policy, indent=2), encoding="utf-8")


def _host_allowed(host: str, allow: list[str]) -> bool:
    host = host.lower()
    for entry in allow:
        entry = entry.lower().strip()
        if host == entry or host.endswith("." + entry):
            return True
    return False


def _check_policy(policy: dict[str, Any], skill_name: str, host: str) -> None:
    mode = str(policy.get("mode", "open"))
    if mode == "local_only":
        raise FirewallBlocked(
            f"netguard mode is 'local_only': all network fetches are blocked "
            f"(skill={skill_name}, host={host})"
        )
    allow_map = policy.get("allow", {})
    allow_list = allow_map.get(skill_name, []) if isinstance(allow_map, dict) else []
    if isinstance(allow_list, list) and allow_list and not _host_allowed(host, allow_list):
        raise FirewallBlocked(f"host '{host}' is not in the allow-list for skill '{skill_name}'")


def _single_get(url: str, timeout: float) -> tuple[bytes, int, str | None]:
    """One HTTP GET; returns (body, status, redirect Location or None)."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    if parsed.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            host, port, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path, headers={"User-Agent": "inzo-privacy-firewall/1.0"})
        response = conn.getresponse()
        body = response.read(_MAX_BODY + 1)
        return body, response.status, response.getheader("Location")
    finally:
        conn.close()


def _fetch_with_policy(
    skill_name: str, url: str, policy: dict[str, Any], timeout: float, hops: int = 0
) -> bytes:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    _check_policy(policy, skill_name, host)  # every hop re-validated
    body, status, location = _single_get(url, timeout)
    if status in (301, 302, 303, 307, 308) and location:
        if hops >= 1:
            raise FirewallBlocked("too many redirects")
        return _fetch_with_policy(
            skill_name, urllib.parse.urljoin(url, location), policy, timeout, hops + 1
        )
    if len(body) > _MAX_BODY:
        raise FirewallBlocked(f"response body exceeds {_MAX_BODY} bytes")
    if status >= 400:
        raise FirewallBlocked(f"fetch failed with HTTP status {status}")
    return body


def guarded_fetch(skill_name: str, url: str, data_dir: Path, timeout: float = 8.0) -> bytes:
    """Fetch ``url`` for ``skill_name`` iff the firewall policy allows it.

    Raises :class:`FirewallBlocked` for non-http(s) URLs, ``local_only``
    mode, hosts outside the skill's allow-list, oversized bodies, and
    HTTP errors. (``data_dir`` locates ``netguard.json``.)
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FirewallBlocked(f"only http(s) URLs are fetchable, got: {parsed.scheme!r}")
    if not (parsed.hostname or "").strip():
        raise FirewallBlocked("URL has no host")
    policy = _load_policy(data_dir)
    return _fetch_with_policy(skill_name, url, policy, timeout)


class PrivacyFirewallSkill(Skill):
    """Manages the per-skill network allowlist (netguard.json)."""

    name = "privacy_firewall"
    description = (
        "Privacy firewall: 'allow <skill> <host>' / 'block <skill> <host>' "
        "manage the per-skill network allowlist; 'status' shows the policy."
    )
    intents = ("firewall.allow", "firewall.status")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "network.fetch")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        message = context.message.strip()
        lowered = message.lower()
        if lowered == "status" or lowered.startswith("status"):
            return self._status(data_dir)
        if lowered.startswith("allow "):
            parts = message.split()
            if len(parts) != 3:
                return "usage: allow <skill> <host>"
            return self._set(data_dir, parts[1], parts[2], allow=True)
        if lowered.startswith("block "):
            parts = message.split()
            if len(parts) != 3:
                return "usage: block <skill> <host>"
            return self._set(data_dir, parts[1], parts[2], allow=False)
        return "privacy_firewall: 'allow <skill> <host>', 'block <skill> <host>', 'status'."

    def _status(self, data_dir: Path) -> str:
        policy = _load_policy(data_dir)
        allow_map = policy.get("allow", {})
        if not isinstance(allow_map, dict):
            allow_map = {}
        lines = [f"privacy firewall status: mode={policy.get('mode', 'open')}"]
        if not allow_map:
            lines.append("no per-skill allow-lists (all hosts allowed unless local_only)")
        for skill_name in sorted(allow_map):
            hosts = allow_map[skill_name]
            lines.append(f"- {skill_name}: {', '.join(hosts) if hosts else '(empty)'}")
        return "\n".join(lines)

    def _set(self, data_dir: Path, skill_name: str, host: str, *, allow: bool) -> str:
        policy = _load_policy(data_dir)
        allow_map = policy.get("allow")
        if not isinstance(allow_map, dict):
            allow_map = {}
            policy["allow"] = allow_map
        hosts = allow_map.get(skill_name, [])
        if not isinstance(hosts, list):
            hosts = []
        host = host.lower().strip()
        if allow:
            if host not in hosts:
                hosts.append(host)
            verb = "allowed"
        else:
            hosts = [h for h in hosts if h != host]
            verb = "blocked"
        allow_map[skill_name] = sorted(hosts)
        _save_policy(data_dir, policy)
        return f"host '{host}' {verb} for skill '{skill_name}'."


SKILLS: list[Skill] = [PrivacyFirewallSkill()]
