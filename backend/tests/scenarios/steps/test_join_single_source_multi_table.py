"""Acceptance test for plan 056: one `sql_database` Source, several tables.

A `Pipeline` used to need one `Source` row per table it read — even when
every table lived behind the same connection. `Pipeline.sources` is now a
list of `SourceTableRef` (`{source_id, table, alias}`), so one Source can be
picked more than once, against different tables, each under its own alias.
This is the end-to-end proof: one real Postgres connection, one Source, a
pipeline that joins three tables off it and aggregates the result.

Requires a reachable Postgres (skipped otherwise, like the integration
suite) — this is the one scenario that can't run against DuckDB/filesystem
fakes, because the whole point is exercising the native ibis postgres
backend via `BackendRegistry.for_connection`.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

from tests.scenarios.helpers import create_connection, create_destination, create_pipeline

pytest.importorskip("psycopg", reason="native postgres ibis backend needs psycopg")


def _pg_url() -> str | None:
    """A plain `postgresql://` URL for the reachable dev Postgres, derived
    from `DTE_DATABASE_URL` (which may carry a `+asyncpg` driver suffix ibis's
    sync backend doesn't understand). `None` when unset — callers skip."""
    raw = os.environ.get("DTE_DATABASE_URL")
    if not raw:
        return None
    return raw.replace("postgresql+asyncpg://", "postgresql://")


def _sync_ibis_connect(url: str):
    import ibis
    parsed = urlparse(url)
    return ibis.postgres.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        database=(parsed.path or "").lstrip("/") or None,
    )


@pytest.fixture
def pg_tables(scenario_ids):
    """Create three real tables (orders/customers/products) in the dev
    Postgres, prefixed uniquely per test, and drop them at teardown."""
    url = _pg_url()
    if not url:
        pytest.skip("DTE_DATABASE_URL not set — no Postgres to test the native backend against")
    con = _sync_ibis_connect(url)

    prefix = scenario_ids("source", "").rstrip("_")
    orders_t = f"{prefix}_orders"
    customers_t = f"{prefix}_customers"
    products_t = f"{prefix}_products"

    # Join columns share names on both sides (customer_id/product_id) —
    # `JoinStep.on` matches ibis's `left[c] == right[c]`, same-name only.
    con.raw_sql(f'''
        CREATE TABLE "{customers_t}" (customer_id INTEGER, name TEXT)
    ''')
    con.raw_sql(f'''
        CREATE TABLE "{products_t}" (product_id INTEGER, name TEXT)
    ''')
    con.raw_sql(f'''
        CREATE TABLE "{orders_t}" (
            id INTEGER, customer_id INTEGER, product_id INTEGER, amount INTEGER
        )
    ''')
    con.raw_sql(f'''
        INSERT INTO "{customers_t}" VALUES (1, 'alice'), (2, 'bob')
    ''')
    con.raw_sql(f'''
        INSERT INTO "{products_t}" VALUES (10, 'widget'), (20, 'gadget')
    ''')
    con.raw_sql(f'''
        INSERT INTO "{orders_t}" VALUES
            (100, 1, 10, 50),
            (101, 1, 20, 30),
            (102, 2, 10, 20)
    ''')
    try:
        yield {
            "url": url,
            "orders": orders_t,
            "customers": customers_t,
            "products": products_t,
        }
    finally:
        con.raw_sql(f'DROP TABLE IF EXISTS "{orders_t}"')
        con.raw_sql(f'DROP TABLE IF EXISTS "{customers_t}"')
        con.raw_sql(f'DROP TABLE IF EXISTS "{products_t}"')


async def test_join_three_tables_off_one_sql_database_source(
    client, scenario_ids, out_dir, pg_tables
):
    """One Source, three refs (aliases), two joins, one aggregate — the
    whole point of plan 056 in one run."""
    conn_id = scenario_ids("connection", "pg")
    src_id = scenario_ids("source", "pgdb")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / "multi_table_join.json"

    await create_connection(
        client, id=conn_id, connection_type="postgres",
        credentials={"url": pg_tables["url"]},
    )
    r = await client.post("/api/sources", json={
        "id": src_id,
        "source_type": "sql_database",
        "connection_id": conn_id,
        "config": {},
        "table": src_id,
    })
    assert r.status_code in (200, 201), r.text

    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )

    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id,
        sources=[
            {"source_id": src_id, "alias": "orders_ref", "table": pg_tables["orders"]},
            {"source_id": src_id, "alias": "customers_ref", "table": pg_tables["customers"]},
            {"source_id": src_id, "alias": "products_ref", "table": pg_tables["products"]},
        ],
        steps=[
            {
                "op": "join",
                "left": "orders_ref", "right": "customers_ref",
                "on": "customer_id", "how": "inner",
                "output_id": "orders_customers",
            },
            {
                "op": "join",
                "left": "orders_customers", "right": "products_ref",
                "on": "product_id", "how": "inner",
                "output_id": "full",
            },
            {
                # `name` is the customer's (join #1, unsuffixed); join #2's
                # `products.name` collides and lands as `name_right`.
                "op": "aggregate",
                "group_by": ["name"],
                "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}],
            },
        ],
        output_id=dst_id,
    )

    # `preview` (not `trigger`) — it shares the exact same
    # resolve/load/compile path plan 056 touches (`_resolve` →
    # `load_source(..., table=ref.table)` → `compile_pipeline`, registry
    # keyed by alias), materialising `compiled.limit(N).execute()` directly
    # in Python rather than through DuckDB's COPY writer. That keeps this
    # test scoped to what plan 056 changed; the writer's handling of a
    # postgres-only compiled expression is a separate, pre-existing seam.
    r = await client.get(f"/api/pipelines/{pipe_id}/preview?limit=20")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None, body

    got = {(row["name"], float(row["total"])) for row in body["rows"]}
    # alice: widget(50) + gadget(30) = 80; bob: widget(20) = 20.
    assert got == {("alice", 80.0), ("bob", 20.0)}
