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


async def test_dry_run_compile_error_returns_422(client, scenario_ids, fixtures_dir, out_dir):
    """A pipeline that references a non-existent column surfaces as 422 with detail."""
    src_id, dst_id, _ = await _seed(client, scenario_ids, fixtures_dir, out_dir, "dry_err.json")
    body = {
        "id": "unsaved_dry_err",
        "name": "Dry err",
        "sources": [src_id],
        "steps": [{"op": "filter", "expr": "no_such_column > 100"}],
        "output_id": dst_id,
    }
    r = await client.post("/api/pipelines/dry-run?limit=5", json=body)
    assert r.status_code == 422, r.text
    body = r.json()
    assert body.get("detail")


