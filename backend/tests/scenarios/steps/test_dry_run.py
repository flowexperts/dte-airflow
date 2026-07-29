"""Scenarios for `POST /api/pipelines/dry-run` (plan 038 item 6).

Dry-run is the unsaved-pipeline sibling of the saved `/preview` endpoint —
same shape (`{rows, count}` on success, 422 with `detail` on compile
failure), but the pipeline body is sent in the request instead of being
loaded by id.
"""
from __future__ import annotations
from tests.scenarios.helpers import (
    create_source, create_destination,
)


async def _seed(client, scenario_ids, fixtures_dir, out_dir, out_name):
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


async def test_dry_run_happy_path(client, scenario_ids, fixtures_dir, out_dir):
    """POST an unsaved pipeline spec → compile + sample; no save required."""
    src_id, dst_id, _ = await _seed(client, scenario_ids, fixtures_dir, out_dir, "dry_ok.json")
    body = {
        "id": "unsaved_dry",  # id is required by PipelineBase; not persisted
        "name": "Dry",
        "sources": [src_id],
        "steps": [
            {"op": "filter", "expr": "amount > 100"},
            {"op": "sort", "by": ["order_id"], "ascending": True},
        ],
        "output_id": dst_id,
    }
    r = await client.post("/api/pipelines/dry-run?limit=5", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["count"] == len(payload["rows"])
    assert payload["count"] > 0
    for row in payload["rows"]:
        assert row["amount"] > 100
    # plan-039: SQL panel — per-step SQL + final compiled SELECT.
    assert "step_sqls" in payload
    assert set(payload["step_sqls"].keys()) == {"0", "1"}
    for sql in payload["step_sqls"].values():
        assert isinstance(sql, str) and sql.strip().upper().startswith("SELECT")
    assert payload.get("final_sql")
    assert payload["final_sql"].strip().upper().startswith("SELECT")
    assert payload.get("error") is None


async def test_dry_run_compile_error_returns_partial_sqls(
    client, scenario_ids, fixtures_dir, out_dir,
):
    """A pipeline whose later step errors still returns 200 with partial
    step_sqls captured up to (but not including) the failing step, plus an
    `error` string describing the failure."""
    src_id, dst_id, _ = await _seed(client, scenario_ids, fixtures_dir, out_dir, "dry_err.json")
    body = {
        "id": "unsaved_dry_err",
        "name": "Dry err",
        "sources": [src_id],
        "steps": [
            {"op": "filter", "expr": "amount > 100"},
            {"op": "filter", "expr": "no_such_column > 100"},
        ],
        "output_id": dst_id,
    }
    r = await client.post("/api/pipelines/dry-run?limit=5", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload.get("error")
    # step 0 succeeded → its SQL should have been captured.
    assert "0" in payload["step_sqls"]
    assert payload["step_sqls"]["0"].strip().upper().startswith("SELECT")
    # step 1 failed → no SQL for it, and no final SQL.
    assert "1" not in payload["step_sqls"]
    assert payload.get("final_sql") is None
    # rows/count is empty (execute never happened).
    assert payload["rows"] == []
    assert payload["count"] == 0


