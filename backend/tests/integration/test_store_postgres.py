import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="requires DATABASE_URL"
)

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dte.store.postgres import PostgresPipelineStore, PostgresRunStore, PostgresSourceStore, PostgresDestinationStore
from dte.models.pipeline import Pipeline, SourceCreate, DestinationCreate, JsonFileTarget


def _pipeline(id: str, name: str = "n", output_id: str = "out") -> Pipeline:
    return Pipeline(id=id, name=name, sources=[], steps=[], output_id=output_id)


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["DATABASE_URL"])
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


async def test_postgres_run_create_and_get(session_factory):
    p_store = PostgresPipelineStore(session_factory)
    r_store = PostgresRunStore(session_factory)
    await p_store.save(_pipeline("pg-rp1"))
    run_id = await r_store.create("pg-rp1")
    run = await r_store.get(run_id)
    assert run["status"] == "pending"
    assert run["pipeline_id"] == "pg-rp1"
    await r_store.delete_for_pipeline("pg-rp1")
    await p_store.delete("pg-rp1")


async def test_postgres_run_update_status(session_factory):
    p_store = PostgresPipelineStore(session_factory)
    r_store = PostgresRunStore(session_factory)
    await p_store.save(_pipeline("pg-rp2"))
    run_id = await r_store.create("pg-rp2")
    await r_store.update(run_id, status="completed", rows_written=42)
    run = await r_store.get(run_id)
    assert run["status"] == "completed"
    assert run["rows_written"] == 42
    await r_store.delete_for_pipeline("pg-rp2")
    await p_store.delete("pg-rp2")


async def test_postgres_run_list_for_pipeline(session_factory):
    p_store = PostgresPipelineStore(session_factory)
    r_store = PostgresRunStore(session_factory)
    await p_store.save(_pipeline("pg-rp3"))
    await r_store.create("pg-rp3")
    await r_store.create("pg-rp3")
    runs = await r_store.list_for_pipeline("pg-rp3")
    assert len(runs) == 2
    await r_store.delete_for_pipeline("pg-rp3")
    await p_store.delete("pg-rp3")


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
    assert result.config.type == "json_file"
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
