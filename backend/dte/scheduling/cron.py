"""Cron next-occurrence computation (plan 047 task 1).

`next_fire_after` is the single primitive both the schedule CRUD API (cron
validation at create/update time) and the ticker (`dte/worker/scheduler.py`)
build on. It always returns exactly the *next* occurrence, never a list —
that is what keeps a schedule from backfilling a backlog of missed runs
after a worker-pool outage (see plan 047, "Missed ticks do not backfill").

Timezone handling: the schedule's `timezone` (an IANA zone name, e.g.
`America/New_York`) is applied via `zoneinfo` before handing a
tz-aware datetime to `croniter`, so DST transitions resolve the way a human
reading the cron expression in that zone would expect:

- Spring forward (a wall-clock hour that doesn't exist): the schedule fires
  once, at the next valid wall-clock time.
- Fall back (a wall-clock hour that occurs twice): the schedule fires once,
  on the *first* occurrence — `croniter` treats the two occurrences as
  distinct UTC instants (different UTC offsets), so asking for "next
  strictly after X" naturally lands on the earlier one first.

The return value is always an aware UTC `datetime`, regardless of the
schedule's timezone or whether the `after` argument was naive (naive input
is treated as UTC — the ticker always calls this with `datetime.now(UTC)`).
"""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterError, croniter


class InvalidCronExpression(ValueError):
    """Raised for a cron expression croniter can't parse, or that isn't
    the standard 5-field form this plan supports."""


class InvalidTimezone(ValueError):
    """Raised for a timezone name zoneinfo doesn't recognise."""


def _validate_five_field(cron_expr: str) -> None:
    fields = cron_expr.split()
    if len(fields) != 5:
        raise InvalidCronExpression(
            f"cron_expr must have exactly 5 fields (minute hour day month "
            f"weekday), got {len(fields)}: {cron_expr!r}"
        )


def next_fire_after(cron_expr: str, tz_name: str, after: datetime) -> datetime:
    """Return the next time `cron_expr` (interpreted in `tz_name`) fires
    strictly after `after`, as an aware UTC datetime.

    Raises `InvalidCronExpression` for a malformed or non-5-field
    expression, `InvalidTimezone` for an unrecognised IANA zone name.
    """
    _validate_five_field(cron_expr)
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise InvalidTimezone(f"unknown timezone: {tz_name!r}") from e

    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    local_after = after.astimezone(tz)

    try:
        it = croniter(cron_expr, local_after)
        next_local = it.get_next(datetime)
    except CroniterError as e:
        raise InvalidCronExpression(f"invalid cron expression {cron_expr!r}: {e}") from e

    return next_local.astimezone(UTC)
