import os

from dte.store.memory import MemoryPipelineStore, MemoryRunStore

_db_url = os.getenv("DATABASE_URL")
if _db_url:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from dte.store.postgres import PostgresPipelineStore, PostgresRunStore

    _engine = create_async_engine(_db_url)
    _factory = async_sessionmaker(_engine, expire_on_commit=False)
    _pipeline_store = PostgresPipelineStore(_factory)
    _run_store = PostgresRunStore(_factory)
else:
    _pipeline_store = MemoryPipelineStore()
    _run_store = MemoryRunStore()


def get_pipeline_store():
    return _pipeline_store


def get_run_store():
    return _run_store
