"""Postgres integration test for batched_update.

Skipped when DTE_DATABASE_URL is unset. Creates a scratch table with 250 rows,
runs the helper, and verifies the row count + termination behaviour.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration

DTE_DATABASE_URL = os.environ.get("DTE_DATABASE_URL")
if DTE_DATABASE_URL is None:
    pytest.skip("DTE_DATABASE_URL unset", allow_module_level=True)


def _sync_url(url: str) -> str:
    """asyncpg URL → psycopg URL for these tests (helper is sync)."""
    return url.replace("+asyncpg", "")


@pytest.fixture()
def scratch_table():
    engine = create_engine(_sync_url(DTE_DATABASE_URL))
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS batched_test"))
        conn.execute(
            text(
                "CREATE TABLE batched_test ("
                "  id text PRIMARY KEY, val text"
                ")"
            )
        )
        conn.execute(
            text("INSERT INTO batched_test (id, val) SELECT gs::text, NULL FROM generate_series(1,250) gs")
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS batched_test"))


def test_batched_update_visits_every_row(scratch_table):
    from dte.alembic_util import batched_update

    op = MagicMock()
    op.get_bind.return_value = scratch_table.connect()

    total = batched_update(
        op,
        table="batched_test",
        set_clause="val = 'done'",
        where_clause="val IS NULL",
        batch_size=50,
    )
    assert total == 250

    with scratch_table.connect() as conn:
        remaining = conn.execute(
            text("SELECT count(*) FROM batched_test WHERE val IS NULL")
        ).scalar()
    assert remaining == 0


def test_batched_update_max_batches(scratch_table):
    from dte.alembic_util import batched_update

    op = MagicMock()
    op.get_bind.return_value = scratch_table.connect()

    total = batched_update(
        op,
        table="batched_test",
        set_clause="val = 'done'",
        where_clause="val IS NULL",
        batch_size=50,
        max_batches=2,
    )
    assert total == 100


def test_batched_update_idempotent(scratch_table):
    """Second run with the same filter finds no rows and returns 0."""
    from dte.alembic_util import batched_update

    op = MagicMock()
    op.get_bind.return_value = scratch_table.connect()

    batched_update(op, table="batched_test", set_clause="val = 'done'",
                   where_clause="val IS NULL", batch_size=50)

    op2 = MagicMock()
    op2.get_bind.return_value = scratch_table.connect()
    total_second = batched_update(op2, table="batched_test", set_clause="val = 'done'",
                                  where_clause="val IS NULL", batch_size=50)
    assert total_second == 0
