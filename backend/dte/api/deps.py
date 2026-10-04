"""Store wiring for FastAPI routes.

Postgres-only: DTE's tables live in the `dte` schema of Airflow's metadata DB
(`dte.airflow.db`). Tests inject fakes via
`app.dependency_overrides[get_pipeline_store] = lambda: FakePipelineStore()`
(see `tests/fakes.py`). Auth and connections come from Airflow.
"""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker

from dte.airflow.auth import get_current_user  # noqa: F401 — re-exported for routes/tests
from dte.airflow.connection_store import AirflowConnectionStore
from dte.airflow.db import async_engine
from dte.store.postgres import (
    PostgresDashboardStore,
    PostgresDestinationStore,
    PostgresEvalExampleStore,
    PostgresEvalSetStore,
    PostgresLookupTableStore,
    PostgresPipelineRevisionStore,
    PostgresPipelineStore,
    PostgresRunEventStore,
    PostgresRunStore,
    PostgresSourceStore,
)


@lru_cache(maxsize=1)
def _session_factory():
    return async_sessionmaker(async_engine(), expire_on_commit=False)


def get_pipeline_store():
    return PostgresPipelineStore(_session_factory())


def get_pipeline_revision_store():
    return PostgresPipelineRevisionStore(_session_factory())


def get_run_store():
    return PostgresRunStore(_session_factory())


def get_run_event_store():
    return PostgresRunEventStore(_session_factory())


def get_dashboard_store():
    return PostgresDashboardStore(_session_factory())


def get_source_store():
    return PostgresSourceStore(_session_factory())


def get_destination_store():
    return PostgresDestinationStore(_session_factory())


def get_connection_store():
    return AirflowConnectionStore()


def get_lookup_table_store():
    return PostgresLookupTableStore(_session_factory())


def get_eval_set_store():
    return PostgresEvalSetStore(_session_factory())


def get_eval_example_store():
    return PostgresEvalExampleStore(_session_factory())


async def get_current_tenant_id() -> str:
    """Tenancy is gone (plan 065); kept so route signatures don't churn."""
    return "default"
