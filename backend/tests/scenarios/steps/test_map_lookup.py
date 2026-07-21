"""Scenarios for the `map` step op in `lookup` mode.

Requires a `LookupTable` in the store (referenced by `lookup_id`).
"""
from __future__ import annotations
from tests.scenarios.helpers import (
    create_source, create_destination, create_pipeline,
    create_lookup_table, trigger_and_wait, read_output_file,
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


async def test_map_lookup_translates_status(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "maplu.json")
    lookup_id = scenario_ids("lookup")
    await create_lookup_table(
        client, id=lookup_id,
        mappings={"paid": "PAID", "pending": "AWAIT", "refunded": "REFUND"},
    )
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "map", "mode": "lookup",
            "field": "status",
            "lookup_id": lookup_id,
            "output_field": "status_code",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    codes = {r["status"]: r["status_code"] for r in rows}
    assert codes["paid"] == "PAID"
    assert codes["pending"] == "AWAIT"
    assert codes["refunded"] == "REFUND"


async def test_map_lookup_default_value(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "maplu_def.json")
    lookup_id = scenario_ids("lookup")
    # Only map paid; everything else falls to default.
    await create_lookup_table(
        client, id=lookup_id,
        mappings={"paid": "ok"},
        default="other",
    )
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "map", "mode": "lookup",
            "field": "status",
            "lookup_id": lookup_id,
            "output_field": "flag",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    for r in rows:
        assert r["flag"] == ("ok" if r["status"] == "paid" else "other")
