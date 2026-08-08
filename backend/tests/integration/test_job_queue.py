"""Real-Postgres coverage for plan 046: transactional enqueue (task 5) and
tenant rehydration through an actual RLS-protected `runs` table (task 4).
Auto-skips when DATABASE_URL is unset — see tests/integration/README
convention in test_store_postgres.py.
"""
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="requires DATABASE_URL"),
]

from dte.models.pipeline import (
    ConnectionBase,
    DestinationCreate,
    Pipeline,
    SourceCreate,
)
from dte.store.postgres import (
    PostgresConnectionStore,
    PostgresDestinationStore,
    PostgresPipelineStore,
    PostgresRunStore,
    PostgresSourceStore,
)


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _close_running_app():
    """The job-queue App singleton persists across tests in-process; force
    it to rebuild each test so DATABASE_URL/env changes take effect and
    tests don't share a pool with stale state."""
    from dte.worker.app import close_running_app

    yield
    await close_running_app()


async def _seed_pipeline(session_factory, suffix: str, tmp_path) -> str:
    # A real, empty-but-scoped directory — not bare "/tmp", which DuckDB's
    # read_json_auto would glob in full (slow/flaky on a shared dev box).
    src_dir = tmp_path / f"src-{suffix}"
    src_dir.mkdir()
    (src_dir / "rows.json").write_text('[{"a": 1}]')

    pid = f"pg-jq-p-{suffix}"
    sid = f"pg-jq-s-{suffix}"
    did = f"pg-jq-d-{suffix}"
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


async def test_enqueue_run_atomic_insert_and_defer(session_factory, tmp_path):
    """`enqueue_run` inserts the run row and defers the job on the same
    psycopg connection/transaction — run.job_id must line up with a real
    `procrastinate_jobs` row carrying the same payload."""
    from dte.worker.tasks import enqueue_run

    pid = await _seed_pipeline(session_factory, uuid.uuid4().hex[:8], tmp_path)

    run_id, job_id = await enqueue_run(pid, None, tenant_id="default")

    r_store = PostgresRunStore(session_factory)
    run = await r_store.get(run_id)
    assert run is not None
    assert run["status"] == "pending"
    assert run["job_id"] == job_id

    async with session_factory() as session:
        result = await session.execute(
            text("SELECT task_name, args, status FROM procrastinate_jobs WHERE id = :id"),
            {"id": job_id},
        )
        job_row = result.mappings().fetchone()
    assert job_row is not None
    assert job_row["task_name"] == "execute_run"
    assert job_row["args"]["run_id"] == run_id
    assert job_row["args"]["pipeline_id"] == pid
    assert job_row["status"] == "todo"

    await r_store.delete_for_pipeline(pid)


async def test_enqueue_run_threads_schedule_id_onto_run_row(session_factory, tmp_path):
    """plan 047 task 4: a run created on behalf of a schedule carries
    schedule_id — the UI's way to distinguish "ran because a human
    clicked" from "ran because it was 2am". A manually-triggered run (no
    schedule_id passed) still lands NULL, unaffected."""
    from dte.models.pipeline import ScheduleBase
    from dte.store.postgres import PostgresScheduleStore
    from dte.worker.tasks import enqueue_run

    pid = await _seed_pipeline(session_factory, uuid.uuid4().hex[:8], tmp_path)
    sch_store = PostgresScheduleStore(session_factory)
    sid = f"sch-{uuid.uuid4().hex[:8]}"
    await sch_store.save(ScheduleBase(
        id=sid, pipeline_id=pid, cron_expr="0 2 * * *", tenant_id="default",
    ))

    run_id, _job_id = await enqueue_run(pid, None, tenant_id="default", schedule_id=sid)

    r_store = PostgresRunStore(session_factory)
    run = await r_store.get(run_id)
    assert run["schedule_id"] == sid

    manual_run_id, _ = await enqueue_run(pid, None, tenant_id="default")
    manual_run = await r_store.get(manual_run_id)
    assert manual_run["schedule_id"] is None

    await r_store.delete_for_pipeline(pid)
    await sch_store.delete(sid)


async def test_execute_run_job_processes_enqueued_run(session_factory, tmp_path):
    """End-to-end: enqueue via `enqueue_run`, then run the worker's job
    body directly (as the worker process would after dequeuing) and check
    the run reaches a terminal state."""
    from dte.worker.tasks import enqueue_run, execute_run_job

    pid = await _seed_pipeline(session_factory, uuid.uuid4().hex[:8], tmp_path)
    run_id, _job_id = await enqueue_run(pid, None, tenant_id="default")

    await execute_run_job(run_id=run_id, pipeline_id=pid, tenant_id="default")

    r_store = PostgresRunStore(session_factory)
    run = await r_store.get(run_id)
    assert run["status"] in ("completed", "failed")  # not stuck pending/running

    await r_store.delete_for_pipeline(pid)
