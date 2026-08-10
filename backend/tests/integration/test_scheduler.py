"""Real-Postgres coverage for the schedule ticker (plan 047 task 5).

Calls `run_tick` directly against real `Postgres*Store` instances rather
than waiting on a live procrastinate worker's real-time minute cron
boundary — the periodic-dispatch mechanism itself (dedup on
`(task_name, periodic_id, defer_timestamp)`) is procrastinate's own
tested machinery; what needs real-Postgres coverage is `run_tick`'s own
SQL (RLS on `schedules`/`runs`, the `enqueue_run` transactional insert,
FK behaviour) — see `tests/unit/test_scheduler_tick.py` for the
store-agnostic behavioural coverage (grace period, overlap, param
resolution) that doesn't need a live database.

Auto-skips when DATABASE_URL is unset.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="requires DATABASE_URL"),
]

from dte.models.pipeline import (
    ConnectionBase,
    DestinationCreate,
    Pipeline,
    ScheduleBase,
    SourceCreate,
)
from dte.store.postgres import (
    PostgresConnectionStore,
    PostgresDestinationStore,
    PostgresPipelineRevisionStore,
    PostgresPipelineStore,
    PostgresRunStore,
    PostgresScheduleStore,
    PostgresSourceStore,
)
from dte.worker.scheduler import run_tick


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _close_running_app():
    """`enqueue_run` opens the job-queue App singleton's psycopg pool on
    first use and never closes it — fine in a long-lived worker process,
    but leaks a pending asyncio task across test teardown here. See the
    identical fixture in tests/integration/test_job_queue.py."""
    from dte.worker.app import close_running_app

    yield
    await close_running_app()


async def _seed_pipeline(session_factory, suffix: str, tmp_path) -> str:
    src_dir = tmp_path / f"src-{suffix}"
    src_dir.mkdir()
    (src_dir / "rows.json").write_text('[{"a": 1}]')

    pid = f"tick-p-{suffix}"
    sid = f"tick-s-{suffix}"
    did = f"tick-d-{suffix}"
    c_store = PostgresConnectionStore(session_factory)
    s_store = PostgresSourceStore(session_factory)
    d_store = PostgresDestinationStore(session_factory)
    p_store = PostgresPipelineStore(session_factory)

    if not await c_store.get("local_fs"):
        await c_store.save(ConnectionBase(id="local_fs", connection_type="local_fs", credentials={}))
    await s_store.save(SourceCreate(
        id=sid, connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": str(src_dir)}, table="rows",
    ))
    await d_store.save(DestinationCreate(
        id=did, connection_id="local_fs",
        config={"type": "json_file", "path": str(tmp_path / f"{did}.json")},
    ))
    await p_store.save(Pipeline(id=pid, name=pid, sources=[sid], steps=[], output_id=did))
    return pid


async def test_run_tick_fires_due_schedule_end_to_end(session_factory, tmp_path):
    suffix = uuid.uuid4().hex[:8]
    pid = await _seed_pipeline(session_factory, suffix, tmp_path)

    sch_store = PostgresScheduleStore(session_factory)
    sid = f"tick-sch-{suffix}"
    now = datetime.now(UTC)
    await sch_store.save(ScheduleBase(
        id=sid, pipeline_id=pid, cron_expr="* * * * *", tenant_id="default",
        next_run_at=now - timedelta(seconds=5),
    ))

    r_store = PostgresRunStore(session_factory)
    p_store = PostgresPipelineStore(session_factory)
    rev_store = PostgresPipelineRevisionStore(session_factory)

    await run_tick(
        sch_store=sch_store, r_store=r_store, p_store=p_store,
        rev_store=rev_store, now=now,
    )

    schedule = await sch_store.get(sid)
    assert schedule.last_run_id is not None
    assert schedule.next_run_at > now

    run = await r_store.get(schedule.last_run_id)
    assert run is not None
    assert run["schedule_id"] == sid
    assert run["status"] == "pending"

    await r_store.delete_for_pipeline(pid)
    await sch_store.delete(sid)


async def test_run_tick_ignores_not_yet_due_schedule(session_factory, tmp_path):
    suffix = uuid.uuid4().hex[:8]
    pid = await _seed_pipeline(session_factory, suffix, tmp_path)

    sch_store = PostgresScheduleStore(session_factory)
    sid = f"tick-future-{suffix}"
    now = datetime.now(UTC)
    await sch_store.save(ScheduleBase(
        id=sid, pipeline_id=pid, cron_expr="* * * * *", tenant_id="default",
        next_run_at=now + timedelta(hours=1),
    ))

    r_store = PostgresRunStore(session_factory)
    p_store = PostgresPipelineStore(session_factory)
    rev_store = PostgresPipelineRevisionStore(session_factory)

    await run_tick(
        sch_store=sch_store, r_store=r_store, p_store=p_store,
        rev_store=rev_store, now=now,
    )

    schedule = await sch_store.get(sid)
    assert schedule.last_run_id is None

    await sch_store.delete(sid)
