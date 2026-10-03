"""GUI automation action validation + append-only action log.

No GUI code lives in this project. Real input injection needs the
:class:`GuiDriver` Protocol implemented outside this codebase.

What IS real and local:

* Action validation — only ``click``/``type``/``press``/``scroll`` are
  allowed; click coordinates are bounded to 0..10000; typed text is capped
  at 2000 chars; ``press`` keys come from an allowlist.
* An append-only action log in the shared ``data_dir/"gui_actions.db"``
  SQLite store recording every validated request with its outcome.

Intents: ``gui.act`` validates, logs, and executes via the driver (a
missing driver refuses with NotConfiguredError); ``gui.log`` validates and
queues the action in the log without executing.
"""

from __future__ import annotations

import re
import shlex
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from skills.base import Skill, SkillContext, SkillError, require_data_dir
from skills.desktop.tray_app import NotConfiguredError

_DB_NAME = "gui_actions.db"
_ALLOWED_ACTIONS = {"click", "type", "press", "scroll"}
_MAX_COORD = 10000
_MAX_TEXT = 2000
_KEY_RE = re.compile(r"^[A-Za-z0-9]$")
_NAMED_KEYS = {
    "enter", "tab", "escape", "esc", "space", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "insert", "ctrl", "alt", "shift", "meta", "super", "cmd", "win",
    *(f"f{n}" for n in range(1, 13)),
}


class GuiDriver(Protocol):
    """OS input-injection integration point (outside this codebase)."""

    def click(self, x: int, y: int) -> None:
        """Click at screen coordinates."""
        ...

    def type_text(self, text: str) -> None:
        """Type text as keystrokes."""
        ...

    def press(self, key: str) -> None:
        """Press a single key."""
        ...


class _UnconfiguredGuiDriver:
    """Placeholder driver that refuses honestly."""

    def click(self, x: int, y: int) -> None:
        raise NotConfiguredError(
            "no GuiDriver configured: inject one via "
            "GuiAutomationSkill(driver=...) implemented outside this codebase."
        )

    def type_text(self, text: str) -> None:
        raise NotConfiguredError("no GuiDriver configured")

    def press(self, key: str) -> None:
        raise NotConfiguredError("no GuiDriver configured")


def validate_action(action: dict[str, object]) -> list[str]:
    """Validate a GUI action dict; return a list of error strings (empty = ok)."""
    errors: list[str] = []
    kind = action.get("kind")
    if kind not in _ALLOWED_ACTIONS:
        return [f"action must be one of {sorted(_ALLOWED_ACTIONS)}"]
    assert isinstance(kind, str)
    if kind == "click":
        for axis in ("x", "y"):
            value = action.get(axis)
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"click needs integer {axis}")
            elif not 0 <= value <= _MAX_COORD:
                errors.append(f"click {axis}={value} out of bounds 0..{_MAX_COORD}")
    elif kind == "type":
        text = action.get("text")
        if not isinstance(text, str) or not text:
            errors.append("type needs non-empty text")
        elif len(text) > _MAX_TEXT:
            errors.append(f"type text too long ({len(text)} > {_MAX_TEXT})")
    elif kind == "press":
        key = action.get("key")
        if not isinstance(key, str):
            errors.append("press needs a key name")
        elif not (_KEY_RE.fullmatch(key) or key.lower() in _NAMED_KEYS):
            errors.append(f"key not in allowlist: {key!r}")
    elif kind == "scroll":
        for axis in ("dx", "dy"):
            value = action.get(axis)
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"scroll needs integer {axis}")
            elif abs(value) > _MAX_COORD:
                errors.append(f"scroll {axis}={value} out of bounds")
    return errors


class _ActionLog:
    """Append-only log of GUI actions in the shared gui_actions.db store."""

    def __init__(self, path: Path) -> None:
        self._path = str(path)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS actions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL, "
                "status TEXT NOT NULL)"
            )

    def append(self, kind: str, detail: str, status: str) -> int:
        with sqlite3.connect(self._path) as conn:
            cur = conn.execute(
                "INSERT INTO actions (ts, kind, detail, status) VALUES (?, ?, ?, ?)",
                (datetime.now(UTC).isoformat(), kind, detail, status),
            )
            row_id = cur.lastrowid
            if row_id is None:
                raise SkillError("sqlite did not return an action id")
            return row_id

    def recent(self, limit: int = 10) -> list[tuple[int, str, str, str, str]]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT id, ts, kind, detail, status FROM actions "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [(int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4])) for r in rows]


def _parse_action(text: str) -> dict[str, object]:
    """Parse 'click x=.. y=..' / 'type text=..' / 'press key=..' / 'scroll dx=.. dy=..'."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty action")
    head, _, rest = stripped.partition(" ")
    kind = head.lower()
    params: dict[str, object] = {"kind": kind}
    if kind == "type":
        # Typed text may contain spaces: take everything after "text=".
        match = re.search(r"text\s*=\s*(.*)$", rest, re.IGNORECASE | re.DOTALL)
        if not match:
            raise ValueError("type needs text=<string> (quote it if it has spaces)")
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        params["text"] = value
        return params
    for token in shlex.split(rest):
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        key = key.strip().lower()
        if key in ("x", "y", "dx", "dy"):
            try:
                params[key] = int(value)
            except ValueError as exc:
                raise ValueError(f"{key} must be an integer: {value!r}") from exc
        else:
            params[key] = value
    return params


class GuiAutomationSkill(Skill):
    """Validates and logs GUI actions; executes via a GuiDriver adapter."""

    name = "gui_automation"
    description = (
        "Validates GUI actions (allowlisted kinds, coordinate bounds, key "
        "allowlist), logs them append-only to gui_actions.db, and executes "
        "via a pluggable GuiDriver."
    )
    intents = ("gui.act", "gui.log")
    required_capabilities = ("skills.execute", "memory.write", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Real input injection needs an OS-specific GuiDriver outside this "
        "codebase: GuiAutomationSkill(driver=...). Validation and the action "
        "log are local; a missing driver refuses instead of faking clicks."
    )

    def __init__(self, driver: GuiDriver | None = None) -> None:
        self._driver: GuiDriver = driver if driver is not None else _UnconfiguredGuiDriver()

    def _log(self, context: SkillContext) -> _ActionLog:
        return _ActionLog(require_data_dir(context) / _DB_NAME)

    def _execute(self, action: dict[str, object]) -> None:
        kind = action["kind"]
        if kind == "click":
            x = action["x"]
            y = action["y"]
            assert isinstance(x, int) and isinstance(y, int)
            self._driver.click(x, y)
        elif kind == "type":
            text = action["text"]
            assert isinstance(text, str)
            self._driver.type_text(text)
        elif kind == "press":
            key = action["key"]
            assert isinstance(key, str)
            self._driver.press(key.lower())
        elif kind == "scroll":
            raise NotConfiguredError("scroll is logged but has no driver method yet")

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("gui.log"):
            mode, payload = "log", text[len("gui.log") :].strip()
        elif lowered.startswith("gui.act"):
            mode, payload = "act", text[len("gui.act") :].strip()
        elif lowered in ("log", "recent"):
            rows = self._log(context).recent()
            if not rows:
                return "gui action log is empty"
            return "recent gui actions:\n" + "\n".join(
                f"#{rid} {ts} {kind} {detail} [{status}]"
                for rid, ts, kind, detail, status in rows
            )
        else:
            mode, payload = "act", text
        try:
            action = _parse_action(payload)
        except ValueError as exc:
            return f"gui action error: {exc}"
        errors = validate_action(action)
        log = self._log(context)
        kind = str(action["kind"])
        detail = " ".join(f"{k}={v}" for k, v in action.items() if k != "kind")
        if errors:
            log.append(kind, detail, "rejected: " + "; ".join(errors))
            return "gui action rejected:\n- " + "\n- ".join(errors)
        if mode == "log":
            rid = log.append(kind, detail, "queued")
            return f"gui action queued (#{rid}): {kind} {detail}"
        try:
            self._execute(action)
        except NotConfiguredError as exc:
            log.append(kind, detail, f"refused: {exc}")
            return f"gui action refused (no driver configured): {exc}"
        log.append(kind, detail, "executed")
        return f"gui action executed: {kind} {detail}"


SKILLS: list[Skill] = [GuiAutomationSkill()]
