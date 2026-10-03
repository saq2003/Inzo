"""Morning briefing: calendar + cached headlines + weather, once a day.

Composes a briefing from ``data_dir/"calendar.db"`` (today's events,
read-only; a missing file is tolerated), headline cache in
``data_dir/"news.db"`` (written by the news digest skill; missing is
tolerated), and a ``WeatherAdapter`` Protocol. The bundled stub makes
the weather section honestly report "unavailable — plug an adapter".
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol

from skills.base import Skill, SkillContext, SkillError, require_data_dir

_EVENT_TABLES = ("events", "event", "calendar", "appointments")


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


class WeatherAdapter(Protocol):
    """Plug-in point for a real weather provider (no hard-coded vendor)."""

    def current(self, location: str) -> str:
        """Return a one-line current-conditions summary for ``location``."""
        ...


class UnconfiguredWeather:
    """Ships with the skill; fails honestly instead of inventing weather."""

    def current(self, location: str) -> str:
        raise SkillError(
            "no weather adapter configured — plug a WeatherAdapter into "
            "MorningBriefingSkill for live conditions"
        )


def _read_calendar(data_dir: Path) -> str:
    """Best-effort read of today's events; tolerates a missing calendar.db."""
    path = data_dir / "calendar.db"
    if not path.exists():
        return "no calendar data (calendar.db not found)"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return f"calendar unavailable ({exc})"
    try:
        tables = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        ]
        table = next((t for t in _EVENT_TABLES if t in tables), "")
        if not table:
            return "calendar.db present but no readable events table"
        today = datetime.now().strftime("%Y-%m-%d")
        matches: list[str] = []
        for row in conn.execute(f"SELECT * FROM {table}"):  # noqa: S608 — table from fixed allowlist
            values = [str(v) for v in row if v is not None]
            if any(today in v for v in values):
                matches.append(" | ".join(values[:4]))
                if len(matches) >= 5:
                    break
    except sqlite3.Error as exc:
        return f"calendar read failed ({exc})"
    finally:
        conn.close()
    if not matches:
        return "no events scheduled today"
    return "; ".join(matches)


def _read_headlines(data_dir: Path, limit: int = 5) -> list[str]:
    """Top cached headlines from news.db; empty when the cache is missing."""
    path = data_dir / "news.db"
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            "SELECT title, source FROM news_items ORDER BY fetched_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [f"{str(r[0])} ({str(r[1])})" for r in rows]


class MorningBriefingSkill(Skill):
    """Composes and delivers the daily morning briefing."""

    name = "morning_briefing"
    description = (
        "Builds a morning briefing from today's calendar events, cached "
        "news headlines, and weather (via adapter); notifies once delivered."
    )
    intents = ("briefing.now",)
    required_capabilities = ("skills.execute", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 86400.0

    def __init__(self, weather: WeatherAdapter | None = None) -> None:
        self._weather: WeatherAdapter = weather or UnconfiguredWeather()

    def set_weather(self, weather: WeatherAdapter) -> None:
        """Attach a real weather provider implementation."""
        self._weather = weather

    def _weather_line(self) -> str:
        try:
            return self._weather.current("home")
        except SkillError as exc:
            return f"weather unavailable — {exc}"

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        today = datetime.now().strftime("%A, %d %B %Y")
        lines = [f"Good morning — {today}", "", "Calendar:", _read_calendar(data_dir), "", "Headlines:"]
        headlines = _read_headlines(data_dir)
        if headlines:
            lines.extend(f"{i + 1}. {h}" for i, h in enumerate(headlines))
        else:
            lines.append("(no cached headlines — run the news digest first)")
        lines.extend(["", "Weather:", self._weather_line()])
        briefing = "\n".join(lines)
        return briefing + _notify(context, "Morning briefing ready")


SKILLS: list[Skill] = [MorningBriefingSkill()]
