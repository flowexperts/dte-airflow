"""Plan 062: `step-schemas` carries dialect feedback for raw-SQL steps.

The builder already debounce-fetches this endpoint on every edit, so the
readback beside each expression rides on a request that was happening
anyway. These are the payload guarantees the editors depend on.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

from tests.scenarios.helpers import create_connection, create_destination, create_source

pytest.importorskip("psycopg", reason="native postgres ibis backend needs psycopg")


def _pg_url() -> str | None:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        return None
    return raw.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
def pg_people(scenario_ids):
    """One real Postgres table, so the compiled pipeline is bound to the
    native postgres backend rather than DuckDB."""
    url = _pg_url()
    if not url:
        pytest.skip("DATABASE_URL not set — no Postgres to bind against")
    import ibis
    p = urlparse(url)
    con = ibis.postgres.connect(
        host=p.hostname or "localhost", port=p.port or 5432, user=p.username,
        password=p.password, database=(p.path or "").lstrip("/") or None,
    )
    table = f"{scenario_ids('source', '').rstrip('_')}_people"
    con.raw_sql(f'CREATE TABLE "{table}" (name TEXT, dob DATE)')
    con.raw_sql(f"""INSERT INTO "{table}" VALUES ('alice','1990-04-02')""")
    try:
        yield {"url": url, "table": table}
    finally:
        con.raw_sql(f'DROP TABLE IF EXISTS "{table}"')


async def _pg_pipeline_body(client, scenario_ids, out_dir, pg_people, steps):
    conn_id = scenario_ids("connection", "pg")
    src_id = scenario_ids("source", "pgdb")
    dst_id = scenario_ids("destination", "out")
    await create_connection(
        client, id=conn_id, connection_type="postgres",
        credentials={"url": pg_people["url"]},
    )
    r = await client.post("/api/sources", json={
        "id": src_id, "source_type": "sql_database", "connection_id": conn_id,
        "config": {}, "table": src_id,
    })
    assert r.status_code in (200, 201), r.text
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_dir / "o.json")},
    )
    return {
        "id": scenario_ids("pipeline"),
        "name": "dialect feedback",
        "sources": [{"source_id": src_id, "alias": "people",
                     "table": pg_people["table"]}],
        "steps": steps,
        "output_id": dst_id,
    }


async def test_step_schemas_reports_dialect_and_transpiled_fragment(
    client, scenario_ids, out_dir, pg_people
):
    body = await _pg_pipeline_body(client, scenario_ids, out_dir, pg_people, [
        {"op": "map", "mode": "expression", "output_field": "age",
         "expr": "date_diff('year', dob, current_date)"},
    ])
    r = await client.post("/api/pipelines/step-schemas", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()

    assert payload["dialect"] == "postgres"
    # The fragment alone, as postgres receives it — not the WITH … SELECT *
    # blob, which is not what the user typed and not what belongs beside it.
    assert "AGE(" in payload["step_expr_sql"]["0"].upper()
    assert [w["code"] for w in payload["warnings"]] == [
        "date_diff_calendar_vs_anniversary"
    ]
    assert payload["warnings"][0]["step"] == 0


async def test_duckdb_pipeline_gets_no_dialect_noise(
    client, scenario_ids, fixtures_dir, out_dir
):
    """The common case stays silent: nothing to transpile, nothing to warn."""
    src_id = scenario_ids("source", "orders")
    dst_id = scenario_ids("destination", "out")
    await create_source(
        client, id=src_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"},
        table="orders",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_dir / "o.json")},
    )
    r = await client.post("/api/pipelines/step-schemas", json={
        "id": scenario_ids("pipeline"), "name": "duck",
        "sources": [{"source_id": src_id, "alias": "orders"}],
        "steps": [{"op": "filter", "expr": "amount > 100"}],
        "output_id": dst_id,
    })
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["dialect"] == "duckdb"
    assert payload["step_expr_sql"] == {}
    assert payload["warnings"] == []
    assert payload["error_step"] is None


async def test_step_schemas_attributes_a_failure_to_its_step(
    client, scenario_ids, fixtures_dir, out_dir
):
    """An unknown column in step 2 must name step 2, not the pipeline."""
    src_id = scenario_ids("source", "orders")
    dst_id = scenario_ids("destination", "out")
    await create_source(
        client, id=src_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"},
        table="orders",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_dir / "o.json")},
    )
    r = await client.post("/api/pipelines/step-schemas", json={
        "id": scenario_ids("pipeline"), "name": "boom",
        "sources": [{"source_id": src_id, "alias": "orders"}],
        "steps": [
            {"op": "filter", "expr": "amount > 0"},
            {"op": "filter", "expr": "no_such_column > 1"},
        ],
        "output_id": dst_id,
    })
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["error_step"] == 1
    assert payload["error"]
    # Step 0 compiled, so its schema is still returned — the editor keeps
    # working above the failure.
    assert "0" in payload["step_schemas"]
