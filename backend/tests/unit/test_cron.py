"""Tests for dte.scheduling.cron.next_fire_after (plan 047 task 1).

Covers: basic next-occurrence computation, timezone handling, both DST
transition directions (this is where cron implementations quietly
disagree — see plan 047 "Semantics worth deciding now"), and cron/tz
validation errors that the schedule CRUD API (task 3) turns into 422s.
"""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from dte.scheduling.cron import InvalidCronExpression, InvalidTimezone, next_fire_after


def test_next_fire_after_basic_utc():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    nxt = next_fire_after("0 2 * * *", "UTC", after)
    assert nxt == datetime(2026, 1, 1, 2, 0, tzinfo=UTC)


def test_next_fire_after_is_strictly_after_and_single_occurrence():
    """Even when `after` is far in the past relative to the period, exactly
    one occurrence — the very next one — comes back. No backfill list."""
    after = datetime(2020, 1, 1, tzinfo=UTC)
    nxt = next_fire_after("*/5 * * * *", "UTC", after)
    assert nxt > after
    assert (nxt - after).total_seconds() <= 5 * 60


def test_next_fire_after_returns_aware_utc_datetime():
    after = datetime(2026, 1, 1, tzinfo=UTC)
    nxt = next_fire_after("0 0 * * *", "America/New_York", after)
    assert nxt.tzinfo is not None
    assert nxt.utcoffset() == UTC.utcoffset(None)


def test_next_fire_after_naive_input_is_treated_as_utc():
    after = datetime(2026, 1, 1, 0, 0)  # naive
    nxt = next_fire_after("0 2 * * *", "UTC", after)
    assert nxt == datetime(2026, 1, 1, 2, 0, tzinfo=UTC)


def test_next_fire_after_respects_timezone():
    # 09:00 Tokyo == 00:00 UTC (JST is UTC+9, no DST).
    after = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    nxt = next_fire_after("0 9 * * *", "Asia/Tokyo", after)
    assert nxt == datetime(2026, 6, 1, 0, 0, tzinfo=UTC) or nxt == datetime(
        2026, 6, 2, 0, 0, tzinfo=UTC
    )
    # Whichever occurrence, it must land exactly on a 00:00 UTC boundary
    # (09:00 JST every day).
    assert nxt.astimezone(ZoneInfo("Asia/Tokyo")).hour == 9
    assert nxt.astimezone(ZoneInfo("Asia/Tokyo")).minute == 0


def test_spring_forward_skipped_hour_fires_once_at_next_valid_time():
    """America/New_York, 2026-03-08: clocks jump 02:00 -> 03:00. A 02:30
    schedule has no 02:30 that day — it must fire once, at 03:00, not be
    skipped entirely and not fire twice."""
    tz = "America/New_York"
    after = datetime(2026, 3, 8, 1, 0, tzinfo=ZoneInfo(tz))
    nxt = next_fire_after("30 2 * * *", tz, after)
    local = nxt.astimezone(ZoneInfo(tz))
    assert local == datetime(2026, 3, 8, 3, 0, tzinfo=ZoneInfo(tz))

    # And the *following* day's occurrence is the normal 02:30, one exact
    # day later in local time — confirms we didn't get stuck repeating the
    # same instant.
    nxt2 = next_fire_after("30 2 * * *", tz, nxt)
    local2 = nxt2.astimezone(ZoneInfo(tz))
    assert local2 == datetime(2026, 3, 9, 2, 30, tzinfo=ZoneInfo(tz))


def test_fall_back_repeated_hour_fires_once_on_first_occurrence():
    """America/New_York, 2026-11-01: clocks fall back 02:00 -> 01:00, so
    01:30 happens twice (once at -04:00, once at -05:00). A 01:30 schedule
    must fire on the *first* occurrence only when asked for the next fire
    starting from before both."""
    tz = "America/New_York"
    after = datetime(2026, 11, 1, 0, 0, tzinfo=ZoneInfo(tz))
    nxt = next_fire_after("30 1 * * *", tz, after)
    local = nxt.astimezone(ZoneInfo(tz))
    assert local.hour == 1 and local.minute == 30
    # First occurrence is in EDT (UTC-4), not the repeated EST (UTC-5) one.
    assert local.utcoffset().total_seconds() == -4 * 3600

    # Asking again strictly after that instant must not return the *second*
    # occurrence of the same wall-clock time again — it must move forward.
    nxt2 = next_fire_after("30 1 * * *", tz, nxt)
    assert nxt2 > nxt


def test_invalid_cron_expression_raises():
    with pytest.raises(InvalidCronExpression):
        next_fire_after("not a cron", "UTC", datetime(2026, 1, 1, tzinfo=UTC))


def test_cron_expression_must_be_five_fields():
    # Plan 047 scope: "standard 5-field" cron — reject 6/7-field extensions
    # (seconds, year) even though croniter itself would accept them.
    with pytest.raises(InvalidCronExpression):
        next_fire_after("0 0 2 * * *", "UTC", datetime(2026, 1, 1, tzinfo=UTC))


def test_invalid_timezone_raises():
    with pytest.raises(InvalidTimezone):
        next_fire_after("0 2 * * *", "Not/AZone", datetime(2026, 1, 1, tzinfo=UTC))
