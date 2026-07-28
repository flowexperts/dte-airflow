"""Error-path scenarios.

Each test verifies the API returns a *sensible* failure — either a 4xx on
save/trigger, or `run.status == "failed"` with a non-empty `error` string
after trigger — for a known-broken pipeline configuration. The goal is to
guarantee we do not surface stack traces, silently return NaN, or hang.
"""
from __future__ import annotations
import pytest

from tests.scenarios.helpers import (
    create_source, create_destination, create_pipeline,
    trigger_and_wait,
)


async def _seed_orders(client, scenario_ids, fixtures_dir, out_dir, out_name="err.json"):
    src_id = scenario_ids("source", "orders")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / out_name
    await create_source(
        client, id=src_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"},
        table="orders",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )
    return src_id, dst_id, out_path


async def _seed_products(client, scenario_ids, fixtures_dir):
    products_id = scenario_ids("source", "products")
    await create_source(
        client, id=products_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "products.json"},
        table="products",
    )
    return products_id


async def test_filter_on_missing_field_fails_run(client, scenario_ids, fixtures_dir, out_dir):
    """A filter referencing a column that doesn't exist should surface a
    non-empty error on the run — not hang, not stack-trace."""
    src_id, dst_id, _ = await _seed_orders(client, scenario_ids, fixtures_dir, out_dir, "err_filter.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "nonexistent_column > 100"}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "failed", run
    assert run["error"], "expected non-empty error string"


async def test_retype_string_to_int_with_bad_content_fails_run(
    client, scenario_ids, fixtures_dir, out_dir
):
    """Casting a string column with non-numeric content to int must fail
    the run explicitly — not silently produce NULL / NaN."""
    src_id, dst_id, _ = await _seed_orders(client, scenario_ids, fixtures_dir, out_dir, "err_retype.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        # status = "paid" | "pending" | "refunded" — none of them cast to int.
        steps=[{"op": "retype", "field": "status", "to_type": "int"}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "failed", run
    assert run["error"], "expected non-empty error string"


async def test_select_empty_fields_and_empty_drop_rejected(
    client, scenario_ids, fixtures_dir, out_dir
):
    """SelectStep validator forbids empty `fields` + empty `drop`.
    The API returns 422 at pipeline save time — the pipeline never runs.
    """
    src_id, dst_id, _ = await _seed_orders(client, scenario_ids, fixtures_dir, out_dir, "err_select.json")
    pipe_id = scenario_ids("pipeline")
    r = await client.post(
        "/api/pipelines",
        json={
            "id": pipe_id,
            "name": pipe_id,
            "sources": [src_id],
            "steps": [{"op": "select", "fields": []}],
            "output_id": dst_id,
        },
    )
    assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"


async def test_join_right_side_not_in_sources_fails(
    client, scenario_ids, fixtures_dir, out_dir
):
    """`right` id must either be one of the pipeline's `sources` or a
    previously-produced join `output_id`. Referencing something unknown
    should not silently succeed."""
    src_id, dst_id, _ = await _seed_orders(client, scenario_ids, fixtures_dir, out_dir, "err_join.json")
    pipe_id = scenario_ids("pipeline")
    # Do NOT include products in sources; reference it anyway.
    ok = await client.post(
        "/api/pipelines",
        json={
            "id": pipe_id,
            "name": pipe_id,
            "sources": [src_id],
            "steps": [{
                "op": "join",
                "left": src_id,
                "right": "no_such_source",
                "on": "product_id",
                "how": "inner",
                "output_id": "joined",
            }],
            "output_id": dst_id,
        },
    )
    # Either the API rejects the save (422/400) or the run fails cleanly.
    if ok.status_code in (200, 201):
        scenario_ids.pipelines  # already tracked via ids
        run = await trigger_and_wait(client, pipe_id)
        assert run["status"] == "failed", run
        assert run["error"], "expected non-empty error string"
    else:
        assert ok.status_code in (400, 422), f"unexpected: {ok.status_code} {ok.text}"


async def test_pivot_on_missing_values_column_fails(
    client, scenario_ids, fixtures_dir, out_dir
):
    """Pivot references a `values` column via raw SQL — if the column
    doesn't exist we should get a failed run with a real error message."""
    src_id, dst_id, _ = await _seed_orders(client, scenario_ids, fixtures_dir, out_dir, "err_pivot.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "pivot",
            "index": "customer_id",
            "columns": "status",
            "values": "no_such_amount",
            "agg": "sum",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "failed", run
    assert run["error"], "expected non-empty error string"


# ─── Engine × connection-type gating ────────────────────────────────────


async def test_pipeline_with_bigquery_source_and_duckdb_engine_rejected_at_save(
    client, scenario_ids, fixtures_dir, out_dir
):
    """A pipeline whose source is a bigquery connection must not save with
    engine=duckdb — duckdb can't read bigquery in our architecture. Expect
    a 422 with a structured `engine_incompatible` payload."""
    from tests.scenarios.helpers import create_connection

    conn_id = scenario_ids("connection", "bq")
    src_id = scenario_ids("source", "bq_orders")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / "err_engine.json"

    await create_connection(
        client, id=conn_id, connection_type="bigquery",
        credentials={"url": "bigquery://my-project/my-dataset"},
    )
    await create_source(
        client, id=src_id, source_type="sql_database", connection_id=conn_id,
        config={"table": "orders"}, table="bq_orders",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )

    pipe_id = scenario_ids("pipeline")
    r = await client.post("/api/pipelines", json={
        "id": pipe_id,
        "name": pipe_id,
        "sources": [src_id],
        "output_id": dst_id,
        "steps": [],
        "engine": "duckdb",  # explicit override that can't handle bigquery
    })
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "engine_incompatible"
    assert detail["engine"] == "duckdb"
    assert any(s["connection_type"] == "bigquery" for s in detail["incompatible_sources"])


async def test_pipeline_with_trino_engine_when_disabled_returns_helpful_422(
    client, scenario_ids, fixtures_dir, out_dir, monkeypatch
):
    """engine=trino without DTE_TRINO_ENABLED=true should fail at save
    with a distinct `trino_not_enabled` code, not a generic ValueError."""
    from tests.scenarios.helpers import create_connection

    monkeypatch.delenv("DTE_TRINO_ENABLED", raising=False)

    conn_id = scenario_ids("connection", "pg_conn")
    src_id = scenario_ids("source", "pg_users")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / "err_trino.json"

    await create_connection(
        client, id=conn_id, connection_type="postgres",
        credentials={"url": "postgresql://u:p@h/db"},
    )
    await create_source(
        client, id=src_id, source_type="sql_database", connection_id=conn_id,
        config={"table": "users"}, table="pg_users",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )

    pipe_id = scenario_ids("pipeline")
    r = await client.post("/api/pipelines", json={
        "id": pipe_id,
        "name": pipe_id,
        "sources": [src_id],
        "output_id": dst_id,
        "steps": [],
        "engine": "trino",
    })
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "trino_not_enabled"
