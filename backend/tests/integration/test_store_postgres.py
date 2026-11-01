import os
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DTE_DATABASE_URL"), reason="requires DTE_DATABASE_URL"),
]

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dte.store.postgres import PostgresPipelineStore, PostgresRunStore, PostgresSourceStore, PostgresDestinationStore
from dte.models.pipeline import Pipeline, SourceCreate, DestinationCreate, JsonFileTarget


def _pipeline(id: str, name: str = "n", output_id: str = "out") -> Pipeline:
    return Pipeline(id=id, name=name, sources=[], steps=[], output_id=output_id)


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["DTE_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_postgres_pipeline_save_and_get(session_factory):
    store = PostgresPipelineStore(session_factory)
    await store.save(_pipeline("pg-p1", "pg test"))
    result = await store.get("pg-p1")
    assert result.id == "pg-p1"
    assert result.name == "pg test"
    await store.delete("pg-p1")


async def test_postgres_pipeline_get_missing_returns_none(session_factory):
    store = PostgresPipelineStore(session_factory)
    result = await store.get("nonexistent")
    assert result is None


async def test_postgres_pipeline_delete(session_factory):
    store = PostgresPipelineStore(session_factory)
    await store.save(_pipeline("pg-del", "delete me"))
    deleted = await store.delete("pg-del")
    assert deleted is True
    assert await store.get("pg-del") is None


def _fake_dag_runs(*runs):
    """Airflow's side of a run (plan 075): DTE's database has no `dag_run`."""
    async def reader(dag_ids=None, run_id=None):
        return [{"run_id": r, "dag_id": d, "state": st, "queued_at": None, "start_date": None,
                 "end_date": None, "run_type": "manual", "conf": {}}
                for r, d, st in runs
                if (dag_ids is None or d in dag_ids) and (run_id is None or r == run_id)]
    return reader


async def test_postgres_runs_merge_dag_runs_with_run_results(session_factory):
    from sqlalchemy import text
    r_store = PostgresRunStore(session_factory, dag_runs=_fake_dag_runs(
        ("pg-r1", "dte__pg-rp1", "success"), ("pg-r2", "dte__pg-rp1", "queued")))
    async with session_factory() as s:
        await s.execute(text("INSERT INTO run_results (run_id, dag_id, pipeline_id, status, rows_written) "
                             "VALUES ('pg-r1', 'dte__pg-rp1', 'pg-rp1', 'completed_with_warnings', 42)"))
        await s.commit()
    try:
        run = await r_store.get("pg-r1")
        assert run["status"] == "completed_with_warnings"
        assert run["rows_written"] == 42
        assert (await r_store.get("pg-r2"))["status"] == "pending"
        assert len(await r_store.list_for_pipeline("pg-rp1")) == 2
    finally:
        assert await r_store.delete_for_pipeline("pg-rp1") == 1


def _source(id: str, table: str = "t") -> SourceCreate:
    return SourceCreate(
        id=id,
        connection_id="local_fs",
        source_type="filesystem",
        config={"bucket_url": "/tmp", "file_glob": "*.json"},
        table=table,
    )


async def test_postgres_source_save_and_get(session_factory):
    store = PostgresSourceStore(session_factory)
    await store.save(_source("pg-src1", "orders"))
    result = await store.get("pg-src1")
    assert result is not None
    assert result.id == "pg-src1"
    assert result.source_type == "filesystem"
    assert result.table == "orders"
    assert result.connection_id == "local_fs"
    # Verify the DB column is `table_name`, not `table`
    from sqlalchemy import text
    async with session_factory() as s:
        row = (await s.execute(text("SELECT table_name FROM sources WHERE id = 'pg-src1'"))).fetchone()
    assert row is not None
    assert row[0] == "orders"
    await store.delete("pg-src1")


async def test_postgres_source_list(session_factory):
    store = PostgresSourceStore(session_factory)
    await store.save(_source("pg-src-l1"))
    await store.save(_source("pg-src-l2"))
    sources = await store.list(limit=10)
    ids = {s.id for s in sources}
    assert {"pg-src-l1", "pg-src-l2"}.issubset(ids)
    await store.delete("pg-src-l1")
    await store.delete("pg-src-l2")


async def test_postgres_source_delete(session_factory):
    store = PostgresSourceStore(session_factory)
    await store.save(_source("pg-src-del"))
    deleted = await store.delete("pg-src-del")
    assert deleted is True
    assert await store.get("pg-src-del") is None


async def test_postgres_source_upsert(session_factory):
    """Re-saving with the same id updates the row (upsert semantics)."""
    store = PostgresSourceStore(session_factory)
    await store.save(_source("pg-src-up", "before"))
    await store.save(_source("pg-src-up", "after"))
    result = await store.get("pg-src-up")
    assert result.table == "after"
    await store.delete("pg-src-up")


def _destination(id: str, path: str = "/tmp/out.json") -> DestinationCreate:
    return DestinationCreate(
        id=id,
        connection_id="local_fs",
        config={"type": "json_file", "path": path},
    )


async def test_postgres_destination_save_and_get(session_factory):
    store = PostgresDestinationStore(session_factory)
    await store.save(_destination("pg-dest1"))
    result = await store.get("pg-dest1")
    assert result is not None
    assert result.id == "pg-dest1"
    # config is narrowed to typed OutputTarget union by narrow_config()
    assert isinstance(result.config, JsonFileTarget)
    # "json_file" is a legacy alias normalised to the unified "json" target.
    assert result.config.type == "json"
    assert result.config.path == "/tmp/out.json"
    assert result.connection_id == "local_fs"
    await store.delete("pg-dest1")


async def test_postgres_destination_list(session_factory):
    store = PostgresDestinationStore(session_factory)
    await store.save(_destination("pg-dest-l1"))
    await store.save(_destination("pg-dest-l2"))
    dests = await store.list(limit=10)
    ids = {d.id for d in dests}
    assert {"pg-dest-l1", "pg-dest-l2"}.issubset(ids)
    # All items have typed configs
    for d in dests:
        if d.id in {"pg-dest-l1", "pg-dest-l2"}:
            assert isinstance(d.config, JsonFileTarget)
    await store.delete("pg-dest-l1")
    await store.delete("pg-dest-l2")


async def test_postgres_destination_upsert(session_factory):
    """Re-saving with the same id updates the row (upsert semantics)."""
    store = PostgresDestinationStore(session_factory)
    await store.save(_destination("pg-dest-up", "/tmp/before.json"))
    await store.save(_destination("pg-dest-up", "/tmp/after.json"))
    result = await store.get("pg-dest-up")
    assert result.config.path == "/tmp/after.json"
    await store.delete("pg-dest-up")


async def test_postgres_destination_delete(session_factory):
    store = PostgresDestinationStore(session_factory)
    await store.save(_destination("pg-dest-del"))
    deleted = await store.delete("pg-dest-del")
    assert deleted is True
    assert await store.get("pg-dest-del") is None


async def test_postgres_pipeline_update_preserves_pipeline_type(session_factory):
    """Re-saving must carry `pipeline_type` and `matrix` through.

    The upsert's ON CONFLICT set was hand-written and omitted both, so a
    pipeline converted to another type reverted to whatever it was inserted
    as. The fake store is a dict and could never show this — it only
    reproduces against a real ON CONFLICT (plan 064).
    """
    store = PostgresPipelineStore(session_factory)
    p = _pipeline("pg-ptype", "typed", output_id="out")
    await store.save(p)

    p.pipeline_type = "viz"
    p.output_id = None
    p.matrix = {"provider": ["claude", "regex"]}
    await store.save(p)

    reloaded = await store.get("pg-ptype")
    assert reloaded.pipeline_type == "viz"
    assert reloaded.matrix == {"provider": ["claude", "regex"]}
    assert reloaded.output_id is None
    await store.delete("pg-ptype")


async def test_postgres_pipeline_notifications_round_trip(session_factory):
    """Plan 070: `pipelines.notifications` JSONB (migration 041)."""
    store = PostgresPipelineStore(session_factory)
    p = _pipeline("pg-notify", "notify a")
    p.notifications = [{"notifier": "x.Y", "params": {"a": 1}, "on": ["failure"]}]
    await store.save(p)
    assert (await store.get("pg-notify")).notifications == p.notifications
    await store.save(_pipeline("pg-notify-none", "notify b"))
    assert (await store.get("pg-notify-none")).notifications == []
    await store.delete("pg-notify")
    await store.delete("pg-notify-none")
