"""Appliance scheduling skill (hardware-gated, real schedule + energy math).

The ``SmartPlug`` Protocol is the plug-in point: a real implementation
flips physical outlets. The bundled ``StubPlug`` raises ``NotConfigured``
so the dispatcher never pretends an appliance changed state. Schedule
entries ``{appliance, on_time, off_time, watts}`` live in
``data_dir/"home.db"``; the 60-second tick dispatcher flips due states via
the adapter, and the energy math (watts × hours → kWh) is fully real.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore, SQLiteKVStore

SCHEDULES_KEY = "appliance:schedules"
LAST_STATE_KEY = "appliance:last_state"
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


class NotConfigured(Exception):
    """Raised by stub adapters when no real hardware backend is plugged in."""


class SmartPlug(Protocol):
    """Plug-in point: real smart-plug implementation.

    Attach with ``ApplianceScheduleSkill.set_plug``.
    """

    def set_state(self, appliance_id: str, on: bool) -> None:
        """Turn the given appliance's plug on or off."""
        ...


class StubPlug:
    """Ships with the skill; always fails honestly."""

    def set_state(self, appliance_id: str, on: bool) -> None:
        raise NotConfigured(
            "no smart plug configured — plug a SmartPlug implementation "
            "via ApplianceScheduleSkill.set_plug"
        )


def _parse_time(value: str) -> tuple[int, int]:
    """Parse 'HH:MM'; raise ValueError on bad input."""
    match = TIME_RE.match(value.strip())
    if not match:
        raise ValueError(f"bad time {value!r}: expected HH:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"bad time {value!r}: hour 0-23, minute 0-59")
    return hour, minute


def _window_hours(on: str, off: str) -> float:
    """Daily on-hours for an on_time→off_time window (overnight-aware)."""
    on_h, on_m = _parse_time(on)
    off_h, off_m = _parse_time(off)
    start = on_h + on_m / 60.0
    end = off_h + off_m / 60.0
    if end <= start:  # overnight window
        end += 24.0
    return end - start


def _should_be_on(on: str, off: str, now: datetime) -> bool:
    """True when ``now`` falls inside the daily on-window (overnight-aware)."""
    on_h, on_m = _parse_time(on)
    off_h, off_m = _parse_time(off)
    start = on_h + on_m / 60.0
    end = off_h + off_m / 60.0
    current = now.hour + now.minute / 60.0
    if end <= start:
        return current >= start or current < end
    return start <= current < end


class ApplianceScheduleSkill(Skill):
    """Schedules appliances on smart plugs and estimates energy use."""

    name = "appliance_schedule"
    description = (
        "Schedules appliances with on/off times, dispatches plug state "
        "changes on a 60-second tick, and estimates daily energy use in kWh."
    )
    intents = ("appliance.schedule", "appliance.list")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Requires real smart plugs. Implement the SmartPlug Protocol "
        "(set_state) and attach via ApplianceScheduleSkill.set_plug; "
        "the bundled StubPlug raises NotConfigured."
    )
    tick_interval_s = 60.0

    def __init__(self) -> None:
        self._plug: SmartPlug = StubPlug()

    def set_plug(self, plug: SmartPlug) -> None:
        """Attach a real smart-plug implementation."""
        self._plug = plug

    def _store(self, context: SkillContext) -> tuple[SQLiteKVStore, SQLiteDocumentStore]:
        path = require_data_dir(context) / "home.db"
        return SQLiteKVStore(path), SQLiteDocumentStore(path)

    def _schedules(self, context: SkillContext) -> list[dict[str, Any]]:
        kv, _ = self._store(context)
        raw = kv.get(SCHEDULES_KEY)
        if not raw:
            return []
        return [cast("dict[str, Any]", d) for d in cast("list[object]", json.loads(raw))]

    def _save_schedules(self, context: SkillContext, schedules: list[dict[str, Any]]) -> None:
        kv, _ = self._store(context)
        kv.put(SCHEDULES_KEY, json.dumps(schedules))

    def _last_states(self, context: SkillContext) -> dict[str, bool]:
        kv, _ = self._store(context)
        raw = kv.get(LAST_STATE_KEY)
        if not raw:
            return {}
        return {k: bool(v) for k, v in cast("dict[str, object]", json.loads(raw)).items()}

    def _save_last_states(self, context: SkillContext, states: dict[str, bool]) -> None:
        kv, _ = self._store(context)
        kv.put(LAST_STATE_KEY, json.dumps(states))

    def _dispatch_tick(self, context: SkillContext) -> str:
        """Flip every schedule whose desired state changed since last tick."""
        now = datetime.now(UTC).astimezone()
        schedules = self._schedules(context)
        if not schedules:
            return "tick: no schedules configured"
        last = self._last_states(context)
        outcomes: list[str] = []
        for sched in schedules:
            appliance = str(sched["appliance"])
            try:
                desired = _should_be_on(str(sched["on_time"]), str(sched["off_time"]), now)
            except ValueError as exc:
                outcomes.append(f"{appliance}: invalid schedule ({exc})")
                continue
            if last.get(appliance) == desired:
                outcomes.append(f"{appliance}: unchanged ({'on' if desired else 'off'})")
                continue
            try:
                self._plug.set_state(appliance, desired)
            except NotConfigured as exc:
                outcomes.append(f"{appliance}: NOT flipped — {exc}")
                continue
            last[appliance] = desired
            outcomes.append(f"{appliance}: flipped {'on' if desired else 'off'}")
        self._save_last_states(context, last)
        return "tick:\n" + "\n".join(outcomes)

    def _energy_report(self, context: SkillContext) -> str:
        schedules = self._schedules(context)
        if not schedules:
            return "no schedules configured — nothing to estimate"
        lines: list[str] = []
        total = 0.0
        for sched in schedules:
            watts = float(sched.get("watts", 0.0))
            hours = _window_hours(str(sched["on_time"]), str(sched["off_time"]))
            kwh = watts * hours / 1000.0
            total += kwh
            lines.append(f"{sched['appliance']}: {watts:.0f} W × {hours:.2f} h = {kwh:.3f} kWh/day")
        lines.append(f"total: {total:.3f} kWh/day")
        return "\n".join(lines)

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lower = text.lower()

        if lower in ("tick", "dispatch"):
            return self._dispatch_tick(context)

        if lower == "energy":
            return self._energy_report(context)

        if lower in ("list", "appliances"):
            schedules = self._schedules(context)
            if not schedules:
                return "no appliance schedules — 'schedule <name> on HH:MM off HH:MM watts <N>'"
            return "\n".join(
                f"{s['appliance']}: {s['on_time']} → {s['off_time']}, {s.get('watts', 0)} W"
                for s in schedules
            )

        if lower.startswith("schedule "):
            # "schedule <name> on HH:MM off HH:MM [watts N]"
            parts = text.split()
            tokens = [p.lower() for p in parts]
            try:
                name = parts[1]
                on_idx = tokens.index("on")
                off_idx = tokens.index("off")
                on_time, off_time = parts[on_idx + 1], parts[off_idx + 1]
                watts = 0.0
                if "watts" in tokens:
                    watts = float(parts[tokens.index("watts") + 1])
            except (IndexError, ValueError) as exc:
                return f"usage: schedule <name> on HH:MM off HH:MM [watts N] ({exc})"
            try:
                _parse_time(on_time)
                _parse_time(off_time)
            except ValueError as exc:
                return str(exc)
            schedules = self._schedules(context)
            schedules = [s for s in schedules if s["appliance"] != name]
            schedules.append(
                {"appliance": name, "on_time": on_time, "off_time": off_time, "watts": watts}
            )
            self._save_schedules(context, schedules)
            hours = _window_hours(on_time, off_time)
            return (
                f"scheduled {name}: {on_time} → {off_time} "
                f"({watts:.0f} W, {hours:.2f} h/day, {watts * hours / 1000:.3f} kWh/day)"
            )

        return (
            "appliance: 'schedule <name> on HH:MM off HH:MM [watts N]', 'list', "
            f"'energy', 'tick'. plug: "
            f"{'configured' if not isinstance(self._plug, StubPlug) else 'NOT configured'}"
        )


SKILLS: list[Skill] = [ApplianceScheduleSkill()]
