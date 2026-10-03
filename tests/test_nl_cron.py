"""Tests for natural-language schedule parsing and next-run math (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.nl_cron import KIND_DAILY, KIND_INTERVAL, KIND_WEEKLY, next_run, parse_nl_schedule


def test_parse_har_subah_8_baje() -> None:
    """'har subah 8 baje' parses to daily 08:00."""
    spec = parse_nl_schedule("har subah 8 baje")
    assert spec.kind == KIND_DAILY
    assert (spec.hour, spec.minute) == (8, 0)


def test_parse_roz_shaam_7_baje() -> None:
    """'roz shaam 7 baje' parses to daily 19:00."""
    spec = parse_nl_schedule("roz shaam 7 baje")
    assert spec.kind == KIND_DAILY
    assert (spec.hour, spec.minute) == (19, 0)


def test_parse_har_30_minute_me() -> None:
    """'har 30 minute me' parses to a 30-minute interval."""
    spec = parse_nl_schedule("har 30 minute me")
    assert spec.kind == KIND_INTERVAL
    assert spec.interval_seconds == pytest.approx(1800.0)


def test_parse_har_ghante() -> None:
    """'har ghante' parses to a one-hour interval."""
    spec = parse_nl_schedule("har ghante")
    assert spec.kind == KIND_INTERVAL
    assert spec.interval_seconds == pytest.approx(3600.0)


def test_parse_every_5_minutes() -> None:
    """'every 5 minutes' parses to a 5-minute interval."""
    spec = parse_nl_schedule("every 5 minutes")
    assert spec.kind == KIND_INTERVAL
    assert spec.interval_seconds == pytest.approx(300.0)


def test_parse_every_weekday_at_9pm() -> None:
    """'every weekday at 9pm' parses to Mon-Fri at 21:00."""
    spec = parse_nl_schedule("every weekday at 9pm")
    assert spec.kind == KIND_WEEKLY
    assert spec.weekdays == (0, 1, 2, 3, 4)
    assert (spec.hour, spec.minute) == (21, 0)


def test_parse_every_monday_at_10am() -> None:
    """'every monday at 10am' parses to Monday at 10:00."""
    spec = parse_nl_schedule("every monday at 10am")
    assert spec.kind == KIND_WEEKLY
    assert spec.weekdays == (0,)
    assert (spec.hour, spec.minute) == (10, 0)


def test_parse_daily_at_8am() -> None:
    """'daily at 8am' parses to daily 08:00."""
    spec = parse_nl_schedule("daily at 8am")
    assert spec.kind == KIND_DAILY
    assert (spec.hour, spec.minute) == (8, 0)


def test_parse_hourly() -> None:
    """'hourly' parses to a one-hour interval."""
    spec = parse_nl_schedule("hourly")
    assert spec.kind == KIND_INTERVAL
    assert spec.interval_seconds == pytest.approx(3600.0)


def test_parse_garbage_raises_value_error() -> None:
    """Unparseable text raises ValueError."""
    with pytest.raises(ValueError):
        parse_nl_schedule("blargle florp nothing at all")
    with pytest.raises(ValueError):
        parse_nl_schedule("")


def test_next_run_interval_is_strictly_after() -> None:
    """Interval schedules land exactly one interval after ``after``."""
    spec = parse_nl_schedule("every 5 minutes")
    after = datetime(2026, 10, 3, 12, 0, 0)
    nxt = next_run(spec, after)
    assert nxt > after
    assert nxt == after + timedelta(seconds=300)


def test_next_run_daily_future_today() -> None:
    """A daily schedule later today fires today."""
    spec = parse_nl_schedule("daily at 8am")
    after = datetime(2026, 10, 3, 6, 0, 0)
    nxt = next_run(spec, after)
    assert nxt > after
    assert (nxt.year, nxt.month, nxt.day, nxt.hour, nxt.minute) == (2026, 10, 3, 8, 0)


def test_next_run_daily_past_time_fires_next_day() -> None:
    """A daily schedule whose time passed today fires at that time tomorrow."""
    spec = parse_nl_schedule("har subah 8 baje")
    after = datetime(2026, 10, 3, 12, 30, 0)
    nxt = next_run(spec, after)
    assert nxt > after
    assert (nxt.year, nxt.month, nxt.day, nxt.hour, nxt.minute) == (2026, 10, 4, 8, 0)


def test_next_run_weekly_matches_spec() -> None:
    """Weekly schedules land on a listed weekday at the listed time."""
    spec = parse_nl_schedule("every monday at 10am")
    # Saturday 2026-10-03; next Monday is 2026-10-05.
    after = datetime(2026, 10, 3, 12, 0, 0)
    nxt = next_run(spec, after)
    assert nxt > after
    assert nxt.weekday() in spec.weekdays
    assert (nxt.hour, nxt.minute) == (10, 0)
    assert nxt.date().isoformat() == "2026-10-05"


def test_next_run_weekly_weekday_same_day_time_passed() -> None:
    """A weekday time already past rolls forward to the next matching day."""
    spec = parse_nl_schedule("every weekday at 9pm")
    # Friday 2026-10-02 22:00: past Friday's slot, so Monday 2026-10-05.
    after = datetime(2026, 10, 2, 22, 0, 0)
    nxt = next_run(spec, after)
    assert nxt > after
    assert nxt.weekday() in spec.weekdays
    assert (nxt.hour, nxt.minute) == (21, 0)


def test_next_run_is_always_strictly_after() -> None:
    """Guard: no spec ever returns a run at or before ``after``."""
    cases = [
        "har subah 8 baje",
        "every 5 minutes",
        "every monday at 10am",
        "hourly",
    ]
    base = datetime(2026, 10, 3, 19, 52, 7)
    for text in cases:
        spec = parse_nl_schedule(text)
        assert next_run(spec, base) > base, text
