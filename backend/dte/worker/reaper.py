"""Stale-run reaper (plan 046 task 8).

A killed worker pod leaves `status=running` forever — the failure mode
`docs/runbooks/oncall/pipeline-stuck-running.md` already documents, more
likely under k8s eviction once execution is split across a worker pool.
The worker touches `runs.last_heartbeat_at` every
`dte.worker.tasks.HEARTBEAT_INTERVAL_SECONDS` while a distributed run is
in flight (see `dte.worker.tasks._heartbeat_loop`); this module
periodically fails out any `running` run whose heartbeat has gone stale
by more than `REAP_THRESHOLD_SECONDS` (2x the heartbeat interval).

Queue-level retry does not cover this case: a DuckDB run is not
idempotent against a destination, so automatically re-executing a
possibly-half-written run could double-write. Reap to `failed` instead;
the user re-triggers.
"""
from __future__ import annotations

import asyncio
import datetime as _dt

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dte.logging import get_logger
from dte.worker.tasks import HEARTBEAT_INTERVAL_SECONDS

REAP_THRESHOLD_SECONDS = HEARTBEAT_INTERVAL_SECONDS * 2
REAP_LOOP_INTERVAL_SECONDS = HEARTBEAT_INTERVAL_SECONDS

_log = get_logger("dte.worker.reaper")


async def reap_stale_runs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    threshold_seconds: float = REAP_THRESHOLD_SECONDS,
) -> list[str]:
    """Fail every `running` run whose heartbeat is older than
    `threshold_seconds` — or was never set at all, i.e. a run that
    started but the worker crashed before its first heartbeat tick (the
    `started_at < cutoff` guard prevents reaping a run that simply hasn't
    reached its first tick yet).

    Bypasses RLS via `SET LOCAL row_security = off` — this is an admin/ops
    query spanning every tenant, the same escape hatch migration 016
    documents and `dte.worker.tasks._fetch_run_actual_tenant_id` uses.

    Returns the list of reaped run ids.
    """
    cutoff = _dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=threshold_seconds)
    async with session_factory() as session:
        await session.execute(text("SET LOCAL row_security = off"))
        result = await session.execute(
            text("""
                UPDATE runs
                   SET status = 'failed',
                       error = 'reaped: worker heartbeat stale (possible pod eviction)'
                 WHERE status = 'running'
                   AND started_at < :cutoff
                   AND (last_heartbeat_at IS NULL OR last_heartbeat_at < :cutoff)
             RETURNING id
            """),
            {"cutoff": cutoff},
        )
        reaped = [row[0] for row in result.fetchall()]
        await session.commit()
    if reaped:
        _log.warning(
            "reaped stale runs",
            extra={"run_ids": reaped, "count": len(reaped)},
        )
    return reaped


async def run_reaper_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    interval_seconds: float = REAP_LOOP_INTERVAL_SECONDS,
) -> None:
    """Run `reap_stale_runs` forever, sleeping `interval_seconds` between
    passes. Intended to run as a background asyncio task alongside the
    worker's `run_worker_async()` — see `dte/worker/__main__.py`. A single
    failed pass is logged and does not stop the loop.
    """
    while True:
        try:
            await reap_stale_runs(session_factory, threshold_seconds=interval_seconds * 2)
        except Exception:
            _log.exception("reaper pass failed")
        await asyncio.sleep(interval_seconds)
