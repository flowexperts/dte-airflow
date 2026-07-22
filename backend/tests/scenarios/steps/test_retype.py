"""Scenarios for the `retype` step op."""
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


async def test_retype_int_to_float(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "retype_f.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "retype", "field": "amount", "to_type": "float"}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # JSON writer emits floats as trailing-.0 numbers
    assert any(isinstance(r["amount"], float) for r in rows)


async def test_retype_int_to_string(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "retype_s.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "retype", "field": "amount", "to_type": "string"}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    assert all(isinstance(r["amount"], str) for r in rows)
    assert "50" in {r["amount"] for r in rows}
