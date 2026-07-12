import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="requires DATABASE_URL"
)

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dte.store.postgres import PostgresPipelineStore, PostgresRunStore


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_postgres_pipeline_save_and_get(session_factory):
    store = PostgresPipelineStore(session_factory)
    pipeline = {"id": "pg-p1", "name": "pg test"}
    await store.save(pipeline)
    result = await store.get("pg-p1")
    assert result["id"] == "pg-p1"
    await store.delete("pg-p1")


async def test_postgres_pipeline_get_missing_returns_none(session_factory):
    store = PostgresPipelineStore(session_factory)
    result = await store.get("nonexistent")
    assert result is None


async def test_postgres_pipeline_delete(session_factory):
    store = PostgresPipelineStore(session_factory)
    await store.save({"id": "pg-del", "name": "delete me"})
    deleted = await store.delete("pg-del")
    assert deleted is True
    result = await store.get("pg-del")
    assert result is None


async def test_postgres_run_create_and_get(session_factory):
    p_store = PostgresPipelineStore(session_factory)
    r_store = PostgresRunStore(session_factory)
    await p_store.save({"id": "pg-rp1", "name": "run pipeline"})
    run_id = await r_store.create("pg-rp1")
    run = await r_store.get(run_id)
    assert run["status"] == "pending"
    assert run["pipeline_id"] == "pg-rp1"
    await p_store.delete("pg-rp1")


async def test_postgres_run_update_status(session_factory):
    p_store = PostgresPipelineStore(session_factory)
    r_store = PostgresRunStore(session_factory)
    await p_store.save({"id": "pg-rp2", "name": "run pipeline 2"})
    run_id = await r_store.create("pg-rp2")
    await r_store.update(run_id, status="completed", rows_written=42)
    run = await r_store.get(run_id)
    assert run["status"] == "completed"
    assert run["rows_written"] == 42
    await p_store.delete("pg-rp2")


async def test_postgres_run_list_for_pipeline(session_factory):
    p_store = PostgresPipelineStore(session_factory)
    r_store = PostgresRunStore(session_factory)
    await p_store.save({"id": "pg-rp3", "name": "run pipeline 3"})
    await r_store.create("pg-rp3")
    await r_store.create("pg-rp3")
    runs = await r_store.list_for_pipeline("pg-rp3")
    assert len(runs) == 2
    await p_store.delete("pg-rp3")
