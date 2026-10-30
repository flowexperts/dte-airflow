"""`list_schemas` / `list_tables` (plan 056) against a real Postgres.

These back `GET /connections/{id}/schemas` and `GET /sources/{id}/tables` —
the "browse instead of typing blind" pickers. Requires a reachable Postgres,
same as the rest of the integration tier.
"""
import os
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DTE_DATABASE_URL"), reason="requires DTE_DATABASE_URL"),
]

from dte.models.pipeline import Connection
from dte.sources.loader import list_schemas, list_tables


def _pg_url() -> str:
    return os.environ["DTE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
def pg_connection() -> Connection:
    return Connection(
        id="c_pg_introspect", connection_type="postgres",
        credentials={"url": _pg_url()},
    )


def test_list_schemas_includes_public(pg_connection):
    schemas = list_schemas(pg_connection, pg_connection.credentials)
    assert "public" in schemas


def test_list_tables_includes_known_app_table(pg_connection):
    """`pipelines` is a table the app's own migrations create (in the `dte`
    schema since plan 065) — a cheap, always-present fixture."""
    tables = list_tables(pg_connection, pg_connection.credentials, schema="dte")
    assert "pipelines" in tables


def test_list_tables_no_schema_arg_still_lists(pg_connection):
    """No schema arg lists the default schema, where alembic keeps its
    version table."""
    tables = list_tables(pg_connection, pg_connection.credentials)
    assert "alembic_version" in tables
