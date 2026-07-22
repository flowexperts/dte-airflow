"""Scenarios for the `sort` step op."""
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


async def test_sort_ascending_by_amount(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "sort1.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "sort", "by": ["amount"], "ascending": True}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    amounts = [r["amount"] for r in rows]
    assert amounts == sorted(amounts)


async def test_sort_descending_by_amount(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "sort2.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "sort", "by": ["amount"], "ascending": False}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    amounts = [r["amount"] for r in rows]
    assert amounts == sorted(amounts, reverse=True)
    assert amounts[0] == 500  # o09


async def test_sort_null_position_default(client, scenario_ids, fixtures_dir, out_dir):
    """SortStep has no nulls_first/nulls_last flag today — assert the
    default (ibis ascending order places NULL last on DuckDB) is stable
    so we notice if the default ever changes.
    """
    src_id = scenario_ids("source", "orders_null")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / "sort_null.json"
    await create_source(
        client, id=src_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders_with_null.json"},
        table="orders_null",
    )
    await create_destination(
        client, id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "sort", "by": ["amount"], "ascending": True}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # The JSON writer emits null-numbers as NaN (float). Normalise both
    # None and NaN to a sentinel so we can reason about position.
    def _is_null(v):
        return v is None or (isinstance(v, float) and v != v)  # NaN != NaN
    amounts = [r["amount"] for r in rows]
    non_null = [a for a in amounts if not _is_null(a)]
    assert non_null == sorted(non_null)
    # DuckDB / ibis ascending default: NULLS LAST.
    assert _is_null(amounts[-1]), f"expected null at tail, got: {amounts}"
    assert sum(1 for a in amounts if _is_null(a)) == 1
    # And the null row is the one we planted (o03).
    assert rows[-1]["order_id"] == "o03"


async def test_sort_multi_column_mixed_direction(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(client, scenario_ids, fixtures_dir, out_dir, "sort3.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "sort", "by": ["customer_id", "amount"], "ascending": [True, False]}],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # Group by customer, verify each group is amount-desc.
    from itertools import groupby
    for _, group in groupby(rows, key=lambda r: r["customer_id"]):
        amounts = [r["amount"] for r in group]
        assert amounts == sorted(amounts, reverse=True), amounts
