"""Scenarios for the `pivot` step op.

Pivot is fragile: goes through `CREATE OR REPLACE TEMP TABLE ... PIVOT`
in DuckDB (see `_apply_pivot` in `dte/compiler/ibis_compiler.py`) —
dynamic PIVOT can't be a view. We assert both column shape and values.
"""
from __future__ import annotations
from tests.scenarios.helpers import (
    create_source, create_destination, create_pipeline,
    trigger_and_wait, read_output_file,
)


async def _seed_orders(client, scenario_ids, fixtures_dir, out_dir, out_name):
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


async def test_pivot_status_by_customer_sum_amount(client, scenario_ids, fixtures_dir, out_dir):
    """Pivot status onto columns, summing amount per customer_id.

    Expected columns: customer_id, paid, pending, refunded.
    """
    src_id, dst_id, out_path = await _seed_orders(client, scenario_ids, fixtures_dir, out_dir, "piv1.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "pivot",
            "index": "customer_id",
            "columns": "status",
            "values": "amount",
            "agg": "sum",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # Column shape.
    keys = set(rows[0].keys())
    assert "customer_id" in keys
    assert {"paid", "pending", "refunded"} <= keys
    # Values per customer. DuckDB PIVOT sum returns DECIMAL which the JSON
    # writer stringifies (see `dte/engine/writers/json_file.py`) — coerce.
    def _num(v):
        return None if v is None else float(v)
    by_cust = {r["customer_id"]: r for r in rows}
    # c1: paid = 50+150+60 = 260, pending = 400, refunded = None
    assert _num(by_cust["c1"]["paid"]) == 260
    assert _num(by_cust["c1"]["pending"]) == 400
    assert by_cust["c1"].get("refunded") in (None, 0)
    # c4: paid = 200+25 = 225, refunded = 250
    assert _num(by_cust["c4"]["paid"]) == 225
    assert _num(by_cust["c4"]["refunded"]) == 250


async def test_pivot_count_agg(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed_orders(client, scenario_ids, fixtures_dir, out_dir, "piv2.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "pivot",
            "index": "customer_id",
            "columns": "status",
            "values": "order_id",
            "agg": "count",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    by_cust = {r["customer_id"]: r for r in rows}
    # c1 has 3 paid, 1 pending, 0 refunded.
    assert by_cust["c1"]["paid"] == 3
    assert by_cust["c1"]["pending"] == 1
