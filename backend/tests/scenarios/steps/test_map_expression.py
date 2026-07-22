"""Scenarios for the `map` step op in `expression` (and `calculation`) mode.

Both modes go through `_apply_expression` — a raw DuckDB SQL fragment that
projects `SELECT *, (<expr>) AS <output_field>`.
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


async def test_map_expression_arithmetic(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "mape1.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "map", "mode": "expression",
            "output_field": "amount_plus_tax",
            "expr": "amount * 1.1",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    by_id = {r["order_id"]: r for r in rows}
    # 50 * 1.1 = 55.0; DuckDB DECIMAL comes through the JSON writer as a
    # string (writer uses `default=str`), so cast to float for compare.
    assert round(float(by_id["o01"]["amount_plus_tax"]), 2) == 55.0
    assert round(float(by_id["o09"]["amount_plus_tax"]), 2) == 550.0


async def test_map_calculation_case_expr(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "mape2.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "map", "mode": "calculation",
            "output_field": "band",
            "expr": "CASE WHEN amount < 100 THEN 'low' WHEN amount < 250 THEN 'mid' ELSE 'high' END",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    by_id = {r["order_id"]: r["band"] for r in rows}
    assert by_id["o01"] == "low"    # 50
    assert by_id["o02"] == "mid"    # 150
    assert by_id["o09"] == "high"   # 500
