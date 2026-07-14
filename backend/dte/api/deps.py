import os

from dte.store.memory import (
    MemoryDestinationStore,
    MemoryPipelineStore,
    MemoryRunStore,
    MemorySourceStore,
)

_db_url = os.getenv("DATABASE_URL")
if _db_url:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from dte.store.postgres import (
        PostgresDestinationStore,
        PostgresPipelineStore,
        PostgresRunStore,
        PostgresSourceStore,
    )

    _engine = create_async_engine(_db_url)
    _factory = async_sessionmaker(_engine, expire_on_commit=False)
    _pipeline_store = PostgresPipelineStore(_factory)
    _run_store = PostgresRunStore(_factory)
    _source_store = PostgresSourceStore(_factory)
    _destination_store = PostgresDestinationStore(_factory)
else:
    _pipeline_store = MemoryPipelineStore()
    _run_store = MemoryRunStore()
    _source_store = MemorySourceStore()
    _destination_store = MemoryDestinationStore()


def get_pipeline_store():
    return _pipeline_store


def get_run_store():
    return _run_store


def get_source_store():
    return _source_store


def get_destination_store():
    return _destination_store
