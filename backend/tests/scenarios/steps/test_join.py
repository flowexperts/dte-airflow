"""Scenarios for the `join` step op.

Note: ibis join output-column order isn't guaranteed. Assertions use row
sets keyed on (order_id, product_name) tuples, per plan constraints.
"""
from __future__ import annotations
from tests.scenarios.helpers import (
    create_source, create_destination, create_pipeline,
    trigger_and_wait, read_output_file,
)


async def _seed_two(client, scenario_ids, fixtures_dir, out_dir, out_name):
    orders_id = scenario_ids("source", "orders")
    products_id = scenario_ids("source", "products")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / out_name
    await create_source(
        client, id=orders_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"},
        table="orders",
    )
    await create_source(
        client, id=products_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "products.json"},
        table="products",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )
    return orders_id, products_id, dst_id, out_path


async def test_join_inner_orders_products(client, scenario_ids, fixtures_dir, out_dir):
    orders_id, products_id, dst_id, out_path = await _seed_two(
        client, scenario_ids, fixtures_dir, out_dir, "join1.json"
    )
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[orders_id, products_id],
        steps=[{
            "op": "join",
            "left": orders_id, "right": products_id,
            "on": "product_id", "how": "inner",
            "output_id": "joined",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # Every order has a matching product → 20 rows.
    assert len(rows) == 20
    # Sanity: every row carries `name` from products.
    assert all("name" in r for r in rows)
    # Row set: (order_id, name).
    got = {(r["order_id"], r["name"]) for r in rows}
    expected_names = {"p1": "Widget", "p2": "Gadget", "p3": "Doohickey",
                      "p4": "Thingamy", "p5": "Whatsit"}
    # rebuild expected from orders → product name.
    from json import loads
    orders = loads((fixtures_dir / "orders.json").read_text())
    expected = {(o["order_id"], expected_names[o["product_id"]]) for o in orders}
    assert got == expected


async def test_join_left_preserves_all_left_rows(client, scenario_ids, fixtures_dir, out_dir):
    """Left join with a filter that limits right side → still all left rows,
    right-only columns null where unmatched."""
    orders_id, products_id, dst_id, out_path = await _seed_two(
        client, scenario_ids, fixtures_dir, out_dir, "join_left.json"
    )
    pipe_id = scenario_ids("pipeline")
    # Filter products down to just p1 BEFORE the join to force unmatched rows.
    await create_pipeline(
        client, id=pipe_id, sources=[orders_id, products_id],
        steps=[
            {"op": "filter", "expr": "product_id = 'p1'"},  # applied on default (orders)
            {
                "op": "join",
                "left": orders_id, "right": products_id,
                "on": "product_id", "how": "left",
                "output_id": "joined",
            },
        ],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # 5 orders have product_id = p1 (o01, o03, o07, o13, o16).
    order_ids = {r["order_id"] for r in rows}
    assert order_ids == {"o01", "o03", "o07", "o13", "o16"}
    for r in rows:
        assert r["name"] == "Widget"
