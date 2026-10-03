"""Temperature monitoring skill (hardware-gated, real logging + alerts).

The ``TempSensor`` Protocol is the plug-in point: a real implementation
reads the room sensor. The bundled ``StubSensor`` raises ``NotConfigured``
so the skill never fabricates readings. Readings are logged to
``data_dir/"home.db"`` and configurable high/low thresholds produce
notifications on the background tick (every 600 s).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore, SQLiteKVStore

CONFIG_KEY = "temp:config"
DEFAULT_HIGH = 35.0
DEFAULT_LOW = 5.0


class NotConfigured(Exception):
    """Raised by stub adapters when no real hardware backend is plugged in."""


class TempSensor(Protocol):
    """Plug-in point: real temperature sensor implementation.

    Attach one with ``TempMonitorSkill.set_sensor``.
    """

    def read_celsius(self) -> float:
        """Return the current temperature in degrees Celsius."""
        ...


class StubSensor:
    """Ships with the skill; always fails honestly."""

    def read_celsius(self) -> float:
        raise NotConfigured(
            "no temperature sensor configured — plug a TempSensor "
            "implementation via TempMonitorSkill.set_sensor"
        )


def _notify(context: SkillContext, text: str) -> str:
    """Send a notification if a notification center is wired; else note it."""
    center = context.notifications
    if center is None:
        return " (notification center unavailable)"
    try:
        center.notify(text)
    except Exception as exc:  # noqa: BLE001 — report, don't crash the tick
        return f" (notify failed: {exc})"
    return " (notified)"


class TempMonitorSkill(Skill):
    """Logs temperature readings and alerts on configurable thresholds."""

    name = "temp_monitor"
    description = (
        "Samples a temperature sensor on a 10-minute tick, logs readings, "
        "and notifies when temperature crosses configurable high/low limits."
    )
    intents = ("temp.status",)
    required_capabilities = (
        "skills.execute",
        "memory.write",
        "memory.read",
        "notify.send",
        "hardware.access",
    )
    background = True
    local_only = False
    adapter_note = (
        "Requires a real temperature sensor. Implement the TempSensor "
        "Protocol (read_celsius) and attach it via TempMonitorSkill.set_sensor; "
        "the bundled StubSensor raises NotConfigured."
    )
    tick_interval_s = 600.0

    def __init__(self) -> None:
        self._sensor: TempSensor = StubSensor()

    def set_sensor(self, sensor: TempSensor) -> None:
        """Attach a real temperature-sensor implementation."""
        self._sensor = sensor

    def _config(self, context: SkillContext) -> dict[str, float]:
        store = SQLiteKVStore(require_data_dir(context) / "home.db")
        raw = store.get(CONFIG_KEY)
        if not raw:
            return {"high": DEFAULT_HIGH, "low": DEFAULT_LOW}
        data = cast("dict[str, float]", json.loads(raw))
        return {
            "high": float(data.get("high", DEFAULT_HIGH)),
            "low": float(data.get("low", DEFAULT_LOW)),
        }

    def _save_config(self, context: SkillContext, high: float, low: float) -> None:
        store = SQLiteKVStore(require_data_dir(context) / "home.db")
        store.put(CONFIG_KEY, json.dumps({"high": high, "low": low}))

    def _log(self, context: SkillContext, celsius: float) -> None:
        store = SQLiteDocumentStore(require_data_dir(context) / "home.db")
        doc: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "celsius": celsius,
            "kind": "temp_reading",
        }
        store.add(doc)

    def _last_readings(self, context: SkillContext, limit: int = 5) -> list[dict[str, Any]]:
        store = SQLiteDocumentStore(require_data_dir(context) / "home.db")
        docs = store.search("temp_reading", limit=50)
        readings = [d for d in docs if d.get("kind") == "temp_reading"]
        readings.sort(key=lambda d: str(d.get("ts", "")), reverse=True)
        return [{k: d.get(k) for k in ("ts", "celsius")} for d in readings[:limit]]

    def _sample(self, context: SkillContext) -> str:
        """One real tick: read, log, check thresholds, notify on breach."""
        try:
            celsius = self._sensor.read_celsius()
        except NotConfigured as exc:
            return f"not configured: {exc} (no reading taken)"
        self._log(context, celsius)
        cfg = self._config(context)
        if celsius > cfg["high"]:
            return f"high temperature alert: {celsius:.1f}°C > {cfg['high']:.1f}°C" + _notify(
                context, f"temperature alert: {celsius:.1f}°C exceeds {cfg['high']:.1f}°C"
            )
        if celsius < cfg["low"]:
            return f"low temperature alert: {celsius:.1f}°C < {cfg['low']:.1f}°C" + _notify(
                context, f"temperature alert: {celsius:.1f}°C below {cfg['low']:.1f}°C"
            )
        return f"temperature ok: {celsius:.1f}°C (limits {cfg['low']:.1f}–{cfg['high']:.1f})"

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip().lower()

        if text in ("tick", "sample", "temp tick"):
            return self._sample(context)

        if text.startswith("set high"):
            cfg = self._config(context)
            try:
                high = float(text.split()[-1])
            except ValueError as exc:
                raise ValueError("high threshold must be a number") from exc
            self._save_config(context, high, cfg["low"])
            return f"high threshold set to {high:.1f}°C"

        if text.startswith("set low"):
            cfg = self._config(context)
            try:
                low = float(text.split()[-1])
            except ValueError as exc:
                raise ValueError("low threshold must be a number") from exc
            self._save_config(context, cfg["high"], low)
            return f"low threshold set to {low:.1f}°C"

        cfg = self._config(context)
        readings = self._last_readings(context)
        lines = [f"thresholds: low {cfg['low']:.1f}°C, high {cfg['high']:.1f}°C"]
        lines.append(
            f"sensor: {'configured' if not isinstance(self._sensor, StubSensor) else 'NOT configured'}"
        )
        if readings:
            latest = cast("dict[str, object]", readings[0])
            lines.append(f"latest: {float(cast(float, latest['celsius'])):.1f}°C at {latest['ts']}")
        else:
            lines.append("no readings logged yet")
        return "\n".join(lines)


SKILLS: list[Skill] = [TempMonitorSkill()]
