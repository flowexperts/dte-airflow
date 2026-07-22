"""Scenarios for `GET /api/pipelines/{id}/preview`.

Preview is a separate compile+execute path from trigger — it materialises
`compiled.limit(N).execute()` and returns rows directly. Compile-time
errors surface as 422 with `detail=str(exc)`, not 500.
"""
from __future__ import annotations
from tests.scenarios.helpers import (
    create_source, create_destination, create_pipeline,
    trigger_and_wait, read_output_file,
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


async def test_preview_matches_trigger_output(client, scenario_ids, fixtures_dir, out_dir):
    """Same pipeline definition: preview and trigger produce identical rows."""
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "prev_ok.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[
            {"op": "filter", "expr": "amount > 100"},
            {"op": "sort", "by": ["order_id"], "ascending": True},
        ],
        output_id=dst_id,
    )
    # Preview.
    r = await client.get(f"/api/pipelines/{pipe_id}/preview?limit=100")
    assert r.status_code == 200, r.text
    preview_body = r.json()
    preview_rows = preview_body["rows"]
    assert preview_body["count"] == len(preview_rows) > 0

    # Trigger → read on-disk output.
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    trigger_rows = read_output_file(out_path)

    # Order matches (both sorted); order_ids sequence should be identical.
    assert [r["order_id"] for r in preview_rows] == [r["order_id"] for r in trigger_rows]


async def test_preview_limit_clips_rows(client, scenario_ids, fixtures_dir, out_dir):
    """Preview respects the ?limit query param."""
    src_id, dst_id, _ = await _seed(client, scenario_ids, fixtures_dir, out_dir, "prev_lim.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "sort", "by": ["order_id"], "ascending": True}],
        output_id=dst_id,
    )
    r = await client.get(f"/api/pipelines/{pipe_id}/preview?limit=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 5
    assert len(body["rows"]) == 5


async def test_preview_returns_422_on_compile_error(client, scenario_ids, fixtures_dir, out_dir):
    """A pipeline that references a non-existent column should surface a
    structured 4xx from preview, not a stack-trace 500."""
    src_id, dst_id, _ = await _seed(client, scenario_ids, fixtures_dir, out_dir, "prev_err.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "no_such_column > 100"}],
        output_id=dst_id,
    )
    r = await client.get(f"/api/pipelines/{pipe_id}/preview?limit=20")
    assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("detail"), "expected non-empty detail on preview error"
