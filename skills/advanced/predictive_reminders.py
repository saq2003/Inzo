"""Predictive reminders from learned time patterns.

Real deterministic logic: reads habit check-ins (``habits.db``) and
reminder history (``reminders.db``), builds per-event hour histograms,
and keeps a pattern when one hour dominates (>=3 occurrences and >=50%
of all occurrences). The next occurrence is predicted at that hour;
the tick fires a pre-reminder 30 minutes before, at most once per day
per pattern. Missing DBs or unrecognized schemas are tolerated.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE_FILE = "predict.db"
_PATTERNS_KEY = "predict:patterns"
_FIRED_KEY = "predict:fired"

_MIN_SUPPORT = 3
_DOMINANCE = 0.5
_PRE_REMIND_MINUTES = 30

_LABEL_HINTS = ("habit", "name", "title", "label", "kind", "event")
_TIME_HINTS = ("time", "date", "created", "_at", "timestamp", "ts", "start")


def _ident(name: str) -> str:
    """Validate a schema-derived identifier for interpolation into SQL.

    Table/column names come from ``PRAGMA table_info`` (the database's
    own schema, not user input); this guard keeps ``noqa: S608`` honest.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def _parse_time(raw: Any) -> datetime | None:
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _read_event_times(path: Path) -> list[tuple[str, datetime]]:
    """Scan a foreign skill DB for (label, timestamp) event pairs.

    Tolerates unknown schemas: every table is tried for a label-like
    column plus a time-like column; unparseable rows are skipped.
    """
    if not path.exists():
        return []
    events: list[tuple[str, datetime]] = []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table,) in rows:
            table = str(table)
            cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            names = [str(c[1]) for c in cols]
            label_col = next((n for n in names if any(h in n.lower() for h in _LABEL_HINTS)), None)
            time_col = next((n for n in names if any(h in n.lower() for h in _TIME_HINTS)), None)
            if not time_col:
                continue
            # Identifiers come from PRAGMA schema info and pass _ident.
            select = (
                f'SELECT "{_ident(label_col)}", "{_ident(time_col)}" '  # noqa: S608
                f'FROM "{_ident(table)}"'
                if label_col
                else f'SELECT "{_ident(time_col)}" FROM "{_ident(table)}"'  # noqa: S608
            )
            try:
                data = conn.execute(select).fetchall()
            except sqlite3.Error:
                continue
            for row in data:
                label_raw, time_raw = (row[0], row[1]) if label_col else (table, row[0])
                moment = _parse_time(time_raw)
                if moment is None:
                    continue
                label = str(label_raw).strip() or table
                events.append((label, moment.astimezone()))
    finally:
        conn.close()
    return events


def _learn_patterns(events: list[tuple[str, datetime]]) -> list[dict[str, Any]]:
    """Cluster event times by hour; keep dominant-hour patterns."""
    by_label: dict[str, list[int]] = {}
    for label, moment in events:
        by_label.setdefault(label, []).append(moment.hour)
    patterns: list[dict[str, Any]] = []
    for label, hours in by_label.items():
        histogram = [0] * 24
        for hour in hours:
            histogram[hour] += 1
        peak_hour = max(range(24), key=lambda h: histogram[h])
        support = histogram[peak_hour]
        total = len(hours)
        if support >= _MIN_SUPPORT and support / total >= _DOMINANCE:
            patterns.append(
                {
                    "label": label,
                    "hour": peak_hour,
                    "support": support,
                    "total": total,
                }
            )
    return sorted(patterns, key=lambda p: str(p["label"]))


def _next_occurrence(hour: int, now: datetime) -> datetime:
    """Next datetime at ``hour`` that is at least 30 min in the future."""
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now + timedelta(minutes=_PRE_REMIND_MINUTES):
        candidate += timedelta(days=1)
    return candidate


async def _notify(context: SkillContext, title: str, body: str) -> bool:
    """Best-effort notification via ``core.notifications.NotificationCenter``."""
    notifier = context.notifications
    if notifier is None:
        return False
    notify = getattr(notifier, "notify", None)
    if not callable(notify):
        return False
    try:
        await notify(title, body)
    except Exception:
        return False
    return True


class PredictiveRemindersSkill(Skill):
    """Learns event time patterns and fires pre-reminders."""

    name = "predictive_reminders"
    description = (
        "Learns when recurring events usually happen (hour histograms) "
        "and fires a pre-reminder 30 min before; 'status' shows patterns."
    )
    intents = ("predict.status",)
    required_capabilities = ("skills.execute", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 600.0

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        message = context.message.strip().lower()
        if message == "tick" or message.startswith("tick"):
            return await self._tick(context, data_dir)
        return self._status(data_dir)

    def _refresh_patterns(self, data_dir: Path) -> list[dict[str, Any]]:
        events: list[tuple[str, datetime]] = []
        events.extend(_read_event_times(data_dir / "habits.db"))
        events.extend(_read_event_times(data_dir / "reminders.db"))
        patterns = _learn_patterns(events)
        store = SQLiteKVStore(data_dir / _STORE_FILE)
        store.put(_PATTERNS_KEY, json.dumps(patterns))
        return patterns

    def _status(self, data_dir: Path) -> str:
        patterns = self._refresh_patterns(data_dir)
        if not patterns:
            return (
                "no time patterns learned yet (need >=3 occurrences of an "
                "event with one dominant hour)."
            )
        now = datetime.now(UTC).astimezone()
        lines = [f"learned time patterns ({len(patterns)}):"]
        for pattern in patterns:
            nxt = _next_occurrence(int(pattern["hour"]), now)
            lines.append(
                f"- {pattern['label']}: usually ~{int(pattern['hour']):02d}:00 "
                f"({pattern['support']}/{pattern['total']} occurrences); "
                f"next predicted {nxt.strftime('%Y-%m-%d %H:%M')}"
            )
        return "\n".join(lines)

    async def _tick(self, context: SkillContext, data_dir: Path) -> str:
        patterns = self._refresh_patterns(data_dir)
        store = SQLiteKVStore(data_dir / _STORE_FILE)
        raw_fired = store.get(_FIRED_KEY)
        fired: set[str] = set(cast("list[str]", json.loads(raw_fired))) if raw_fired else set()
        now = datetime.now(UTC).astimezone()
        sent: list[str] = []
        for pattern in patterns:
            nxt = _next_occurrence(int(pattern["hour"]), now)
            pre = nxt - timedelta(minutes=_PRE_REMIND_MINUTES)
            fired_key = f"{pattern['label']}:{nxt.date().isoformat()}"
            if pre <= now <= nxt and fired_key not in fired:
                title = "upcoming routine"
                body = (
                    f"'{pattern['label']}' usually happens around "
                    f"{int(pattern['hour']):02d}:00 — starting in ~30 min."
                )
                if await _notify(context, title, body):
                    sent.append(str(pattern["label"]))
                fired.add(fired_key)
        store.put(_FIRED_KEY, json.dumps(sorted(fired)[-_MIN_SUPPORT * 100 :]))
        if not sent:
            return "tick: no pre-reminders due."
        return "tick: pre-reminders sent for: " + ", ".join(sent)


SKILLS: list[Skill] = [PredictiveRemindersSkill()]
