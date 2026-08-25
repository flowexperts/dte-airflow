"""Scenarios for the `case` (if/else) step op."""
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


async def test_case_tiers_amount(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "case_tier.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "case",
            "output_field": "tier",
            "branches": [
                {"when": [{"field": "amount", "op": ">=", "value": "200"}],
                 "then": "large"},
                {"when": [{"field": "amount", "op": ">=", "value": "100"}],
                 "then": "medium"},
            ],
            "otherwise": "small",
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    tiers = {r["order_id"]: r["tier"] for r in rows}
    assert tiers["o01"] == "small"     # 50
    assert tiers["o02"] == "medium"    # 150
    assert tiers["o04"] == "large"     # 300
    assert set(tiers.values()) == {"small", "medium", "large"}


async def test_case_without_otherwise_is_null(client, scenario_ids, fixtures_dir, out_dir):
    src_id, dst_id, out_path = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "case_null.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[{
            "op": "case",
            "output_field": "flag",
            "branches": [{
                "when": [{"field": "status", "op": "=", "value": "refunded"}],
                "then": "refund",
            }],
        }],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    assert {r["flag"] for r in rows} == {"refund", None}
    assert all(r["flag"] == "refund" for r in rows if r["status"] == "refunded")


async def test_date_diff_years_from_a_date_column(client, scenario_ids, fixtures_dir, out_dir):
    """age-from-dob, the flow `case` exists to feed."""
    src_id, dst_id, out_path = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "case_age.json")
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[src_id],
        steps=[
            {"op": "date_diff", "field": "ordered_at", "to": "2025-01-15",
             "unit": "year", "output_field": "years_ago"},
            {"op": "case", "output_field": "recent",
             "branches": [{"when": [{"field": "years_ago", "op": "<", "value": "1"}],
                           "then": True}],
             "otherwise": False},
        ],
        output_id=dst_id,
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # Birthday-aware: 2024-01-15 and earlier are a full year before the
    # 2025-01-15 cutoff; 2024-01-16 onwards are not yet.
    ages = {r["order_id"]: r["years_ago"] for r in rows}
    assert ages["o15"] == 1   # ordered 2024-01-15, exactly one year
    assert ages["o16"] == 0   # ordered 2024-01-16, a day short
    recent = {r["order_id"]: r["recent"] for r in rows}
    assert recent["o15"] is False and recent["o16"] is True
