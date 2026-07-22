"""Scenarios that exercise DuckDB STRUCT column access via dot syntax.

Filesystem sources bring nested JSON in as STRUCT columns. The wire form
for a field reference is dot syntax (`customer.name`) — this matches the
struct-member path in DuckDB SQL and is what `_resolve_field` in
`dte/compiler/ibis_compiler.py` traverses.
"""
from __future__ import annotations
from tests.scenarios.helpers import (
    create_source, create_destination, create_pipeline,
    trigger_and_wait, read_output_file,
)


async def _seed(client, scenario_ids, fixtures_dir, out_dir, out_name):
    src_id = scenario_ids("source", "nested")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / out_name
    await create_source(
        client, id=src_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "nested_orders.json"},
        table="nested_orders",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )
    return src_id, dst_id, out_path


async def test_select_dot_path_with_alias(client, scenario_ids, fixtures_dir, out_dir):
    """`customer.name` traversed via struct; alias determines output column."""
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "nested_sel.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "select",
            "fields": [
                {"field": "order_id"},
                {"field": "customer.name", "alias": "cust_name"},
            ],
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    assert set(rows[0].keys()) == {"order_id", "cust_name"}
    by_id = {r["order_id"]: r["cust_name"] for r in rows}
    assert by_id["n01"] == "Alice"
    assert by_id["n03"] == "Bob"
    assert by_id["n06"] == "Eve"


async def test_filter_dot_path_expr(client, scenario_ids, fixtures_dir, out_dir):
    """Filter's raw SQL passes through DuckDB — `customer.name = 'Bob'`
    resolves via struct-member SQL and matches the two Bob rows."""
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "nested_filt.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "customer.name = 'Bob'"}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    assert {r["order_id"] for r in rows} == {"n03", "n07"}


async def test_rename_nested_leaf_to_flat(client, scenario_ids, fixtures_dir, out_dir):
    """Renaming `customer.region → cust_region` — after select-project the
    leaf we can then rename it at the top level."""
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "nested_ren.json")
    pipe_id = scenario_ids("pipeline")
    # First project the nested leaf up to the top level, then rename it.
    # Ibis `rename` only takes flat column names — a nested path can't be
    # a rename source, so the natural pattern is `select → rename`.
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[
            {
                "op": "select",
                "fields": [
                    {"field": "order_id"},
                    {"field": "customer.region"},
                ],
            },
            # `mappings` shape is {old: new} per test_rename.py.
            {"op": "rename", "mappings": {"region": "cust_region"}},
        ],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    keys = set(rows[0].keys())
    assert keys == {"order_id", "cust_region"}
    regions = {r["order_id"]: r["cust_region"] for r in rows}
    assert regions["n01"] == "NA"
    assert regions["n03"] == "EU"
    assert regions["n05"] == "APAC"
