"""Sleep analysis skill (fully local, deterministic).

Parses sleep CSV exports with columns ``start_iso,end_iso[,quality]``
(Apple Health style or any generic export) and computes real statistics:
average sleep duration, bedtime variance, and a 0–100 consistency score
based on the standard deviation of bedtime and of duration. Summaries are
stored in ``data_dir/"health.db"``.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; raise ValueError on bad input."""
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"bad timestamp {value!r}") from exc


@dataclass(frozen=True)
class SleepNight:
    """One parsed night: duration and bedtime in hours, optional quality."""

    duration_h: float
    bedtime_h: float
    quality: float | None


def _parse_csv(csv_text: str) -> list[SleepNight]:
    """Parse sleep CSV; required columns: start_iso, end_iso; optional: quality."""
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise ValueError("empty CSV")
    missing = {"start_iso", "end_iso"} - set(reader.fieldnames)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    rows: list[SleepNight] = []
    for row in reader:
        start = _parse_iso(str(row["start_iso"]))
        end = _parse_iso(str(row["end_iso"]))
        if end <= start:
            raise ValueError(f"end before start: {row['start_iso']!r} → {row['end_iso']!r}")
        duration_h = (end - start).total_seconds() / 3600.0
        bedtime_h = start.hour + start.minute / 60.0 + start.second / 3600.0
        quality: float | None = None
        if "quality" in reader.fieldnames and row.get("quality"):
            try:
                quality = float(str(row["quality"]))
            except ValueError as exc:
                raise ValueError(f"bad quality value {row['quality']!r}") from exc
        rows.append(SleepNight(duration_h=duration_h, bedtime_h=bedtime_h, quality=quality))
    if not rows:
        raise ValueError("no data rows")
    return rows


def _stddev(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def analyze_sleep(csv_text: str) -> dict[str, Any]:
    """Compute sleep stats from CSV text.

    Returns average duration (h), bedtime mean/stddev (h), and a
    consistency score 0–100: 100 minus penalties for bedtime irregularity
    (25 pts per hour of stddev) and duration irregularity (5 pts per hour),
    clamped at 0.
    """
    rows = _parse_csv(csv_text)
    durations = [row.duration_h for row in rows]
    bedtimes = [row.bedtime_h for row in rows]
    bedtime_std = _stddev(bedtimes)
    duration_std = _stddev(durations)
    score = max(0.0, 100.0 - bedtime_std * 25.0 - duration_std * 5.0)
    qualities = [row.quality for row in rows if row.quality is not None]
    result: dict[str, Any] = {
        "nights": len(rows),
        "avg_duration_h": round(sum(durations) / len(durations), 2),
        "avg_bedtime": _fmt_hour(sum(bedtimes) / len(bedtimes)),
        "bedtime_stddev_h": round(bedtime_std, 2),
        "duration_stddev_h": round(duration_std, 2),
        "consistency_score": round(score, 1),
    }
    if qualities:
        result["avg_quality"] = round(sum(qualities) / len(qualities), 2)
    return result


def _fmt_hour(hour: float) -> str:
    hour = hour % 24.0
    return f"{int(hour):02d}:{int(round((hour % 1) * 60)):02d}"


class SleepAnalysisSkill(Skill):
    """Analyzes sleep CSV exports into duration, bedtime, consistency stats."""

    name = "sleep_analysis"
    description = (
        "Parses a sleep CSV export (start_iso,end_iso[,quality]) and reports "
        "average duration, bedtime variance, and a 0-100 consistency score."
    )
    intents = ("sleep.analyze",)
    required_capabilities = ("skills.execute", "memory.write", "system.read")
    background = True
    local_only = True

    def _save_summary(self, context: SkillContext, summary: dict[str, Any]) -> None:
        store = SQLiteDocumentStore(require_data_dir(context) / "health.db")
        store.add({**summary, "kind": "sleep_summary"})

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        payload = text
        for prefix in ("analyze ", "sleep "):
            if text.lower().startswith(prefix):
                payload = text[len(prefix) :].strip()
                break
        # Allow a file path (relative to data_dir) or raw CSV text.
        data_dir = require_data_dir(context)
        candidate = Path(payload)
        if candidate.is_absolute() or "\n" not in payload:
            maybe = data_dir / payload if not candidate.is_absolute() else candidate
            if maybe.is_file():
                try:
                    payload = maybe.read_text(encoding="utf-8")
                except OSError as exc:
                    return f"could not read {maybe}: {exc}"
        if "\n" not in payload and "," not in payload:
            return "usage: analyze <csv text or data_dir-relative path>"
        try:
            summary = analyze_sleep(payload)
        except ValueError as exc:
            return f"could not analyze: {exc}"
        self._save_summary(context, summary)
        lines = [
            f"nights analyzed: {summary['nights']}",
            f"avg duration: {summary['avg_duration_h']} h",
            f"avg bedtime: {summary['avg_bedtime']} (±{summary['bedtime_stddev_h']} h)",
            f"consistency score: {summary['consistency_score']}/100",
        ]
        if "avg_quality" in summary:
            lines.append(f"avg quality: {summary['avg_quality']}")
        return "\n".join(lines)


SKILLS: list[Skill] = [SleepAnalysisSkill()]
