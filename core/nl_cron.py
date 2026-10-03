"""Natural-language schedule parsing (English + Hinglish) and next-run math.

Understands phrases such as ``"har subah 8 baje"`` (daily 08:00),
``"roz shaam 7 baje"`` (daily 19:00), ``"har 30 minute me"`` (every
30 minutes), ``"every weekday at 9pm"`` (Mon-Fri 21:00), or ``"hourly"``.

All datetimes are timezone-naive local time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

#: Schedule kinds produced by :func:`parse_nl_schedule`.
KIND_INTERVAL = "interval"
KIND_DAILY = "daily"
KIND_WEEKLY = "weekly"

_INTERVAL_UNIT_SECONDS: dict[str, float] = {
    "second": 1.0,
    "seconds": 1.0,
    "sec": 1.0,
    "secs": 1.0,
    "minute": 60.0,
    "minutes": 60.0,
    "min": 60.0,
    "mins": 60.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "hr": 3600.0,
    "hrs": 3600.0,
    "ghanta": 3600.0,
    "ghante": 3600.0,
    "day": 86400.0,
    "days": 86400.0,
    "din": 86400.0,
}

_INTERVAL_NUMBERED_RE = re.compile(
    r"(?:\bhar\b|\bevery\b)\s+(\d+(?:\.\d+)?)\s*"
    r"(seconds?|secs?|minutes?|mins?|hours?|hrs?|ghante?|days?|din)\b"
)
_INTERVAL_HOURLY_RES = (
    re.compile(r"\bhourly\b"),
    re.compile(r"\bevery\s+hour\b"),
    re.compile(r"\bhar\s+ghante?\b"),
)

#: weekday index (0=Monday) -> accepted English + Hindi name variants.
_WEEKDAY_NAMES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (0, ("monday", "mon", "somvaar", "somvar")),
    (1, ("tuesday", "tue", "tues", "mangalvaar", "mangalvar", "mangal")),
    (2, ("wednesday", "wed", "budhvaar", "budhvar", "budh")),
    (3, ("thursday", "thu", "thur", "thurs", "guruvaar", "guruwar", "guruvar")),
    (4, ("friday", "fri", "shukravaar", "shukravar", "shukra")),
    (5, ("saturday", "sat", "shanivaar", "shanivar", "shani")),
    (6, ("sunday", "sun", "ravivaar", "ravivar", "ravi")),
)

_WEEKDAY_RE = re.compile(r"\bweekdays?\b")
_WEEKEND_RE = re.compile(r"\bweekends?\b")

_DAILY_HINT_RE = re.compile(
    r"\b(daily|roz|every\s+day|subah|shaam|raat|dopahar|"
    r"morning|evening|night|afternoon)\b"
)
_AM_HINT_RE = re.compile(r"\b(subah|morning)\b")
_PM_HINT_RE = re.compile(r"\b(dopahar|afternoon|shaam|evening|raat|night)\b")
_MIDNIGHT_HINT_RE = re.compile(r"\b(raat|night)\b")

_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(baje|am|pm)\b")


@dataclass(frozen=True)
class ScheduleSpec:
    """Parsed schedule: interval, daily, or weekly recurrence."""

    kind: str  # "interval" | "daily" | "weekly"
    interval_seconds: float | None
    hour: int | None
    minute: int | None
    weekdays: tuple[int, ...]  # 0=Monday; used when kind == "weekly"
    raw: str


def _parse_interval_seconds(normalized: str) -> float | None:
    """Return the interval in seconds, or None when not an interval phrase."""
    for pattern in _INTERVAL_HOURLY_RES:
        if pattern.search(normalized):
            return 3600.0
    match = _INTERVAL_NUMBERED_RE.search(normalized)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    seconds = amount * _INTERVAL_UNIT_SECONDS[unit]
    if seconds <= 0:
        raise ValueError(f"non-positive interval in schedule: {unit}")
    return seconds


def _parse_weekdays(normalized: str) -> tuple[int, ...] | None:
    """Return weekday indexes for weekly phrases, else None."""
    if _WEEKDAY_RE.search(normalized):
        return (0, 1, 2, 3, 4)
    if _WEEKEND_RE.search(normalized):
        return (5, 6)
    found: list[int] = []
    for index, names in _WEEKDAY_NAMES:
        for name in names:
            if re.search(rf"\b{re.escape(name)}\b", normalized):
                if index not in found:
                    found.append(index)
                break
    return tuple(found) if found else None


def _apply_baje_daypart(hour: int, normalized: str) -> int:
    """Apply subah/shaam/raat/dopahar hints to a ``baje`` hour (0-23)."""
    if _AM_HINT_RE.search(normalized):
        return 0 if hour == 12 else hour
    if _PM_HINT_RE.search(normalized):
        if hour == 12:
            # "raat 12 baje" is midnight; "dopahar 12 baje" is noon.
            return 0 if _MIDNIGHT_HINT_RE.search(normalized) else 12
        return hour + 12 if hour < 12 else hour
    return hour


def _parse_time(normalized: str) -> tuple[int, int] | None:
    """Extract ``(hour, minute)`` from time phrases, else None.

    Handles ``"8 baje"``, ``"8:30 baje"``, ``"10am"``, ``"9pm"`` and the
    subah/shaam/raat/dopahar day-part hints.
    """
    match = _TIME_RE.search(normalized)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    marker = match.group(3)
    if minute > 59:
        raise ValueError(f"invalid minutes in schedule: {match.group(0)!r}")
    if marker in ("am", "pm"):
        if not 1 <= hour <= 12:
            raise ValueError(f"invalid hour in schedule: {match.group(0)!r}")
        if marker == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
    else:  # "baje"
        if not 0 <= hour <= 23:
            raise ValueError(f"invalid hour in schedule: {match.group(0)!r}")
        hour = _apply_baje_daypart(hour, normalized)
    return hour, minute


def parse_nl_schedule(text: str) -> ScheduleSpec:
    """Parse an English/Hinglish schedule phrase into a :class:`ScheduleSpec`.

    Examples:
        - ``"har subah 8 baje"`` -> daily 08:00
        - ``"roz shaam 7 baje"`` -> daily 19:00
        - ``"har 30 minute me"`` -> every 1800 seconds
        - ``"har ghante"`` / ``"hourly"`` -> every 3600 seconds
        - ``"every 5 minutes"`` -> every 300 seconds
        - ``"every weekday at 9pm"`` -> weekly Mon-Fri 21:00
        - ``"every monday at 10am"`` -> weekly Monday 10:00
        - ``"daily at 8am"`` -> daily 08:00

    Raises:
        ValueError: when no schedule can be understood in ``text``.
    """
    raw = text
    normalized = text.strip().lower()
    if not normalized:
        raise ValueError("empty schedule text")

    interval_seconds = _parse_interval_seconds(normalized)
    if interval_seconds is not None:
        return ScheduleSpec(
            kind=KIND_INTERVAL,
            interval_seconds=interval_seconds,
            hour=None,
            minute=None,
            weekdays=(),
            raw=raw,
        )

    weekdays = _parse_weekdays(normalized)
    clock = _parse_time(normalized)

    if weekdays is not None:
        if clock is None:
            raise ValueError(f"weekly schedule needs a time: {raw!r}")
        hour, minute = clock
        return ScheduleSpec(
            kind=KIND_WEEKLY,
            interval_seconds=None,
            hour=hour,
            minute=minute,
            weekdays=weekdays,
            raw=raw,
        )

    if _DAILY_HINT_RE.search(normalized) or clock is not None:
        if clock is None:
            raise ValueError(f"daily schedule needs a time: {raw!r}")
        hour, minute = clock
        return ScheduleSpec(
            kind=KIND_DAILY,
            interval_seconds=None,
            hour=hour,
            minute=minute,
            weekdays=(),
            raw=raw,
        )

    raise ValueError(f"could not parse schedule: {raw!r}")


def next_run(spec: ScheduleSpec, after: datetime) -> datetime:
    """Return the next occurrence of ``spec`` strictly after ``after``.

    Datetimes are timezone-naive local time, matching ``after``.
    """
    if spec.kind == KIND_INTERVAL:
        if spec.interval_seconds is None or spec.interval_seconds <= 0:
            raise ValueError(f"interval schedule needs positive seconds: {spec!r}")
        return after + timedelta(seconds=spec.interval_seconds)

    if spec.kind == KIND_DAILY:
        if spec.hour is None or spec.minute is None:
            raise ValueError(f"daily schedule needs a time: {spec!r}")
        candidate = after.replace(
            hour=spec.hour, minute=spec.minute, second=0, microsecond=0
        )
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate

    if spec.kind == KIND_WEEKLY:
        if not spec.weekdays:
            raise ValueError(f"weekly schedule needs weekdays: {spec!r}")
        hour = spec.hour if spec.hour is not None else 0
        minute = spec.minute if spec.minute is not None else 0
        for delta in range(8):
            day = (after + timedelta(days=delta)).date()
            if day.weekday() in spec.weekdays:
                candidate = datetime.combine(day, time(hour, minute))
                if candidate > after:
                    return candidate
        raise ValueError(f"no weekly occurrence found: {spec!r}")

    raise ValueError(f"unknown schedule kind: {spec.kind!r}")
