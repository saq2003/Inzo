"""Background anomaly detection over local numeric series.

Real deterministic logic: z-score anomaly detection (pure function
:func:`zscore_anomalies`) applied to daily spending totals from
``data_dir/"expenses.db"``, sleep durations from ``data_dir/"health.db"``,
and habit check-in gaps from ``data_dir/"habits.db"``. Missing files or
unrecognized schemas are tolerated (series come back empty). The hourly
tick notifies only about *new* anomalies via ``context.notifications``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path
from typing import cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE_FILE = "anomalies.db"
_SEEN_KEY = "anomalies:seen"

# Column-name hints used to locate value/date columns in foreign skill DBs.
_VALUE_HINTS = ("amount", "total", "value", "duration", "hours", "minutes", "count")
_DATE_HINTS = ("date", "day", "created", "_at", "timestamp", "ts", "time", "start")


def zscore_anomalies(values: list[float], threshold: float = 2.5) -> list[int]:
    """Return indices of values whose |z-score| exceeds ``threshold``.

    Pure function: population mean/stddev, no I/O. Needs at least 3
    points and nonzero variance, otherwise no anomaly can be judged.
    """
    if len(values) < 3:
        return []
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    if std == 0:
        return []
    return [i for i, v in enumerate(values) if abs((v - mean) / std) > threshold]


def _ident(name: str) -> str:
    """Validate a schema-derived identifier for interpolation into SQL.

    Table/column names come from ``PRAGMA table_info`` (the database's
    own schema, not user input); this guard keeps ``noqa: S608`` honest.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [str(r[0]) for r in rows]


def _columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [(str(r[1]), str(r[2]).upper()) for r in rows]


def _pick_column(
    columns: list[tuple[str, str]], hints: tuple[str, ...], numeric: bool
) -> str | None:
    for name, coltype in columns:
        lowered = name.lower()
        if not any(h in lowered for h in hints):
            continue
        if numeric and not any(
            t in coltype for t in ("INT", "REAL", "NUM", "DOUBLE", "FLOAT", "DECIMAL")
        ):
            continue
        return name
    return None


def _read_daily_totals(path: Path) -> list[tuple[str, float]]:
    """Generic reader: per-day sums of the first plausible value column.

    Tolerates unknown schemas by scanning every table for a numeric
    column plus a date-like column. Returns [(day_iso, total)] sorted.
    """
    if not path.exists():
        return []
    totals: dict[str, float] = {}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        for table in _tables(conn):
            columns = _columns(conn, table)
            value_col = _pick_column(columns, _VALUE_HINTS, numeric=True)
            date_col = _pick_column(columns, _DATE_HINTS, numeric=False)
            if not value_col or not date_col:
                continue
            try:
                # Identifiers come from PRAGMA schema info and pass _ident.
                rows = conn.execute(
                    f'SELECT "{_ident(date_col)}", "{_ident(value_col)}" '  # noqa: S608
                    f'FROM "{_ident(table)}"'  # noqa: S608
                ).fetchall()
            except sqlite3.Error:
                continue
            for date_raw, value_raw in rows:
                try:
                    day = str(date_raw)[:10]
                    datetime.fromisoformat(day)
                    totals[day] = totals.get(day, 0.0) + float(value_raw)
                except (ValueError, TypeError):
                    continue
            if totals:
                break  # first usable table wins; deterministic
    finally:
        conn.close()
    return sorted(totals.items())


def _read_sleep_durations(path: Path) -> list[tuple[str, float]]:
    """Sleep durations (raw values, not summed) ordered by date."""
    if not path.exists():
        return []
    points: list[tuple[str, float]] = []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        tables = _tables(conn)
        sleep_tables = [t for t in tables if "sleep" in t.lower()] or tables
        for table in sleep_tables:
            columns = _columns(conn, table)
            value_col = _pick_column(columns, _VALUE_HINTS, numeric=True)
            date_col = _pick_column(columns, _DATE_HINTS, numeric=False)
            if not value_col or not date_col:
                continue
            try:
                # Identifiers come from PRAGMA schema info and pass _ident.
                rows = conn.execute(
                    f'SELECT "{_ident(date_col)}", "{_ident(value_col)}" '  # noqa: S608
                    f'FROM "{_ident(table)}" ORDER BY "{_ident(date_col)}"'  # noqa: S608
                ).fetchall()
            except sqlite3.Error:
                continue
            for date_raw, value_raw in rows:
                try:
                    day = str(date_raw)[:10]
                    datetime.fromisoformat(day)
                    points.append((day, float(value_raw)))
                except (ValueError, TypeError):
                    continue
            if points:
                break
    finally:
        conn.close()
    return points


def _read_habit_gaps(path: Path) -> list[tuple[str, float]]:
    """Gaps (in days) between consecutive habit check-in dates."""
    if not path.exists():
        return []
    days: set[str] = set()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        tables = _tables(conn)
        habit_tables = [t for t in tables if "habit" in t.lower() or "checkin" in t.lower()]
        for table in habit_tables or tables:
            columns = _columns(conn, table)
            date_col = _pick_column(columns, _DATE_HINTS, numeric=False)
            if not date_col:
                continue
            try:
                # Identifiers come from PRAGMA schema info and pass _ident.
                rows = conn.execute(
                    f'SELECT "{_ident(date_col)}" FROM "{_ident(table)}"'  # noqa: S608
                ).fetchall()
            except sqlite3.Error:
                continue
            for (date_raw,) in rows:
                try:
                    day = str(date_raw)[:10]
                    datetime.fromisoformat(day)
                    days.add(day)
                except (ValueError, TypeError):
                    continue
            if days:
                break
    finally:
        conn.close()
    ordered = sorted(days)
    gaps: list[tuple[str, float]] = []
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        delta = (datetime.fromisoformat(cur) - datetime.fromisoformat(prev)).days
        gaps.append((cur, float(delta)))
    return gaps


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


class AnomalyDetectSkill(Skill):
    """Z-score anomaly detection over local numeric series."""

    name = "anomaly_detect"
    description = (
        "Detects anomalies (z-score) in spending totals, sleep durations, "
        "and habit check-in gaps; 'check' runs a scan, hourly tick notifies."
    )
    intents = ("anomaly.check",)
    required_capabilities = ("skills.execute", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 3600.0

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        return await self._scan(context, data_dir, notify_new=True)

    async def _scan(self, context: SkillContext, data_dir: Path, *, notify_new: bool) -> str:
        series: dict[str, list[tuple[str, float]]] = {
            "spending": _read_daily_totals(data_dir / "expenses.db"),
            "sleep": _read_sleep_durations(data_dir / "health.db"),
            "habit_gaps": _read_habit_gaps(data_dir / "habits.db"),
        }
        store = SQLiteKVStore(data_dir / _STORE_FILE)
        raw_seen = store.get(_SEEN_KEY)
        seen: set[str] = set(cast("list[str]", json.loads(raw_seen))) if raw_seen else set()

        findings: list[str] = []
        new_anomalies: list[str] = []
        for label, points in series.items():
            values = [v for _, v in points]
            if not values:
                findings.append(f"{label}: no data")
                continue
            indices = zscore_anomalies(values)
            if not indices:
                findings.append(f"{label}: {len(values)} points, no anomalies")
                continue
            for i in indices:
                day, value = points[i]
                mean = statistics.fmean(values)
                std = statistics.pstdev(values)
                z = (value - mean) / std if std else 0.0
                key = f"{label}:{day}:{value:.2f}"
                desc = f"{label} anomaly on {day}: {value:.2f} (mean {mean:.2f}, z={z:+.2f})"
                findings.append(desc)
                if key not in seen:
                    seen.add(key)
                    new_anomalies.append(desc)
        store.put(_SEEN_KEY, json.dumps(sorted(seen)))

        if notify_new:
            for desc in new_anomalies:
                await _notify(context, "anomaly detected", desc)
        lines = ["anomaly scan:"]
        lines.extend(f"- {f}" for f in findings)
        if new_anomalies:
            lines.append(f"new anomalies notified: {len(new_anomalies)}")
        return "\n".join(lines)


SKILLS: list[Skill] = [AnomalyDetectSkill()]
