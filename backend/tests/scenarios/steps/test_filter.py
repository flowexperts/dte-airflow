"""Scenarios for the `filter` step op."""
from __future__ import annotations
from tests.scenarios.helpers import (
    create_source, create_destination, create_pipeline,
    trigger_and_wait, read_output_file,
)


async def _seed_orders(client, scenario_ids, fixtures_dir, out_dir, out_name="filter_out.json"):
    src_id = scenario_ids("source", "orders")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / out_name
    await create_source(
        client,
        id=src_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"},
        table="orders",
    )
    await create_destination(
        client,
        id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )
    return src_id, dst_id, out_path


async def test_filter_numeric_expr_keeps_matching_rows(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed_orders(client, scenario_ids, fixtures_dir, out_dir)
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "amount > 100"}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    got = {r["order_id"] for r in rows}
    expected = {"o02", "o04", "o05", "o07", "o09", "o13", "o14", "o16", "o18"}
    assert got == expected


async def test_filter_string_equality(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed_orders(
        client, scenario_ids, fixtures_dir, out_dir, "filter_status.json"
    )
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "status = 'refunded'"}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    assert {r["order_id"] for r in rows} == {"o06", "o14"}


async def test_filter_compound_expr(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed_orders(
        client, scenario_ids, fixtures_dir, out_dir, "filter_and.json"
    )
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "status = 'paid' AND amount >= 200"}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    assert {r["order_id"] for r in rows} == {"o04", "o07", "o09"}
