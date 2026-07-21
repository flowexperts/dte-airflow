"""Scenarios for the `aggregate` step op."""
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


async def test_aggregate_sum_by_customer(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "agg1.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "aggregate",
            "group_by": ["customer_id"],
            "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}],
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    totals = {r["customer_id"]: r["total"] for r in rows}
    # Hand-computed from orders.json.
    assert totals == {
        "c1": 50 + 150 + 60 + 400,    # 660
        "c2": 75 + 300 + 30 + 20,     # 425
        "c3": 120 + 40 + 175 + 55,    # 390
        "c4": 200 + 25 + 250,         # 475
        "c5": 500 + 90 + 80,          # 670
        "c6": 110 + 45,               # 155
    }


async def test_aggregate_count_distinct_and_max(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "agg2.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "aggregate",
            "group_by": ["status"],
            "aggregations": [
                {"field": "order_id", "func": "count", "alias": "n"},
                {"field": "amount", "func": "max", "alias": "biggest"},
            ],
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    by_status = {r["status"]: r for r in rows}
    assert by_status["paid"]["n"] == 15
    assert by_status["pending"]["n"] == 3
    assert by_status["refunded"]["n"] == 2
    assert by_status["paid"]["biggest"] == 500
    assert by_status["refunded"]["biggest"] == 250
