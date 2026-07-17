"""Store wiring for FastAPI routes.

Postgres-only: `DATABASE_URL` must be set. There is no in-memory
fallback in production code — tests inject fakes via
`app.dependency_overrides[get_pipeline_store] = lambda: FakePipelineStore()`
(see `tests/fakes.py`).
"""
from __future__ import annotations
import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dte.store.postgres import (
    PostgresConnectionStore,
    PostgresDestinationStore,
    PostgresLookupTableStore,
    PostgresPipelineStore,
    PostgresRunStore,
    PostgresSourceStore,
)


@lru_cache(maxsize=1)
def _session_factory():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. dte requires Postgres in every "
            "environment; tests inject stores via app.dependency_overrides."
        )
    engine = create_async_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False)


def get_pipeline_store():
    return PostgresPipelineStore(_session_factory())


def get_run_store():
    return PostgresRunStore(_session_factory())


def get_source_store():
    return PostgresSourceStore(_session_factory())


def get_destination_store():
    return PostgresDestinationStore(_session_factory())


def get_connection_store():
    return PostgresConnectionStore(_session_factory())


def get_lookup_table_store():
    return PostgresLookupTableStore(_session_factory())
