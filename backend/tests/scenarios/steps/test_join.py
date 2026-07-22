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


async def test_join_multi_key(client, scenario_ids, fixtures_dir, out_dir):
    """Join on a composite key (customer_id, product_id). Build a small
    lookup fixture on the fly so keys align exactly with orders rows."""
    import json
    orders_id = scenario_ids("source", "orders")
    lookup_id = scenario_ids("source", "cust_prod")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / "join_multi.json"

    # A composite-key lookup covering three (customer_id, product_id)
    # combinations from orders.json.
    lookup_rows = [
        {"customer_id": "c1", "product_id": "p1", "label": "A"},
        {"customer_id": "c1", "product_id": "p2", "label": "B"},
        {"customer_id": "c2", "product_id": "p1", "label": "C"},
    ]
    (fixtures_dir / "cust_prod.json").write_text(json.dumps(lookup_rows))

    await create_source(
        client, id=orders_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"},
        table="orders",
    )
    await create_source(
        client, id=lookup_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "cust_prod.json"},
        table="cust_prod",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[orders_id, lookup_id],
        steps=[{
            "op": "join",
            "left": orders_id, "right": lookup_id,
            "on": ["customer_id", "product_id"],
            "how": "inner",
            "output_id": "joined",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # Only rows whose (customer_id, product_id) matches the lookup keep.
    # From orders.json: o01(c1,p1)→A, o02(c1,p2)→B, o03(c2,p1)→C.
    labels_by_order = {r["order_id"]: r["label"] for r in rows}
    assert labels_by_order == {"o01": "A", "o02": "B", "o03": "C"}


async def test_join_outer_keeps_unmatched_from_both_sides(
    client, scenario_ids, fixtures_dir, out_dir
):
    """Outer join with a filter that shrinks the left side and a lookup
    fixture with unmatched rows on the right — both sets of unmatched
    rows should appear in the output."""
    import json
    orders_id = scenario_ids("source", "orders")
    extra_id = scenario_ids("source", "extra_products")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / "join_outer.json"

    # A product-labels fixture that includes a product id not in orders.json.
    extra_products = [
        {"product_id": "p1", "label": "widget_lbl"},
        {"product_id": "p999", "label": "orphan_lbl"},
    ]
    (fixtures_dir / "extra_products.json").write_text(json.dumps(extra_products))

    await create_source(
        client, id=orders_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"},
        table="orders",
    )
    await create_source(
        client, id=extra_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "extra_products.json"},
        table="extra_products",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )
    pipe_id = scenario_ids("pipeline")
    # Pre-filter orders to only p1 and p2 → guarantees p2 rows have no
    # right-side match, and p999 on the right has no left-side match.
    await create_pipeline(
        client, id=pipe_id, sources=[orders_id, extra_id],
        steps=[
            {"op": "filter", "expr": "product_id IN ('p1', 'p2')"},
            {
                "op": "join",
                "left": orders_id, "right": extra_id,
                "on": "product_id", "how": "outer",
                "output_id": "joined",
            },
        ],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # Unmatched right: p999 orphan_lbl (no order_id).
    orphan_rights = [r for r in rows if r.get("label") == "orphan_lbl"]
    assert len(orphan_rights) == 1
    # Unmatched left: p2 orders (no label).
    p2_orders = [r for r in rows if r.get("order_id") in {"o02", "o05", "o10", "o17"}]
    assert len(p2_orders) >= 1
    def _is_null(v):
        return v is None or (isinstance(v, float) and v != v)
    for r in p2_orders:
        assert _is_null(r.get("label")), r


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
