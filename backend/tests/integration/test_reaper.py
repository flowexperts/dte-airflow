"""Real-Postgres coverage for the stale-run reaper (plan 046 task 8).
Auto-skips when DATABASE_URL is unset.
"""
import datetime as dt
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="requires DATABASE_URL"),
]

from dte.models.pipeline import Pipeline
from dte.store.postgres import PostgresPipelineStore, PostgresRunStore
from dte.worker.reaper import reap_stale_runs


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_run(session_factory, suffix: str, *, started_at, last_heartbeat_at, status="running") -> str:
    pid = f"pg-reap-p-{suffix}"
    p_store = PostgresPipelineStore(session_factory)
    await p_store.save(Pipeline(id=pid, name=pid, sources=[], steps=[], output_id="out"))

    r_store = PostgresRunStore(session_factory)
    run_id = await r_store.create(pid)
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE runs SET status = :status, started_at = :started_at, "
                "last_heartbeat_at = :hb WHERE id = :id"
            ),
            {"status": status, "started_at": started_at, "hb": last_heartbeat_at, "id": run_id},
        )
        await session.commit()
    return run_id


async def test_reap_fails_run_with_stale_heartbeat(session_factory):
    now = dt.datetime.now(dt.UTC)
    run_id = await _seed_run(
        session_factory, uuid.uuid4().hex[:8],
        started_at=now - dt.timedelta(minutes=5),
        last_heartbeat_at=now - dt.timedelta(minutes=5),
    )

    reaped = await reap_stale_runs(session_factory, threshold_seconds=60)

    assert run_id in reaped
    r_store = PostgresRunStore(session_factory)
    run = await r_store.get(run_id)
    assert run["status"] == "failed"
    assert "reaped" in run["error"]


async def test_reap_ignores_fresh_heartbeat(session_factory):
    now = dt.datetime.now(dt.UTC)
    run_id = await _seed_run(
        session_factory, uuid.uuid4().hex[:8],
        started_at=now - dt.timedelta(minutes=5),
        last_heartbeat_at=now,
    )

    reaped = await reap_stale_runs(session_factory, threshold_seconds=60)

    assert run_id not in reaped
    r_store = PostgresRunStore(session_factory)
    run = await r_store.get(run_id)
    assert run["status"] == "running"


async def test_reap_ignores_recently_started_run_with_no_heartbeat_yet(session_factory):
    """A run that started 5s ago and hasn't ticked its first heartbeat yet
    must not be reaped — only started_at-old AND heartbeat-stale runs are."""
    now = dt.datetime.now(dt.UTC)
    run_id = await _seed_run(
        session_factory, uuid.uuid4().hex[:8],
        started_at=now - dt.timedelta(seconds=5),
        last_heartbeat_at=None,
    )

    reaped = await reap_stale_runs(session_factory, threshold_seconds=60)

    assert run_id not in reaped
    r_store = PostgresRunStore(session_factory)
    run = await r_store.get(run_id)
    assert run["status"] == "running"


async def test_reap_ignores_non_running_statuses(session_factory):
    now = dt.datetime.now(dt.UTC)
    run_id = await _seed_run(
        session_factory, uuid.uuid4().hex[:8],
        started_at=now - dt.timedelta(minutes=5),
        last_heartbeat_at=now - dt.timedelta(minutes=5),
        status="completed",
    )

    reaped = await reap_stale_runs(session_factory, threshold_seconds=60)

    assert run_id not in reaped
