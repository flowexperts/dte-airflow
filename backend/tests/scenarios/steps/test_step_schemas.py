"""Scenarios for `POST /api/pipelines/step-schemas` and filtering on
aggregated columns (plan 038 item 7).

`step-schemas` returns the column list produced at each step index so the
frontend can offer downstream autocomplete for aggregation aliases and
pivot dynamic columns.
"""
from __future__ import annotations
from tests.scenarios.helpers import (
    create_source, create_destination,
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


async def test_filter_on_aggregated_alias(client, scenario_ids, fixtures_dir, out_dir):
    """Item 7 core: filter after aggregate references the new alias column."""
    src_id, dst_id, _ = await _seed(client, scenario_ids, fixtures_dir, out_dir, "agg_filter.json")
    body = {
        "id": "unsaved_agg_filter",
        "name": "Agg + Filter",
        "sources": [src_id],
        "steps": [
            {
                "op": "aggregate",
                "group_by": ["customer_id"],
                "aggregations": [{"field": "amount", "func": "sum", "alias": "total_amount"}],
            },
            {"op": "filter", "expr": "total_amount > 500"},
        ],
        "output_id": dst_id,
    }
    r = await client.post("/api/pipelines/dry-run?limit=100", json=body)
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert len(rows) > 0
    for row in rows:
        assert float(row["total_amount"]) > 500


async def test_step_schemas_reports_per_step_columns(client, scenario_ids, fixtures_dir, out_dir):
    """/step-schemas returns column names produced at each step index."""
    src_id, dst_id, _ = await _seed(client, scenario_ids, fixtures_dir, out_dir, "ss.json")
    body = {
        "id": "unsaved_ss",
        "name": "Step schemas",
        "sources": [src_id],
        "steps": [
            {"op": "filter", "expr": "amount > 0"},
            {
                "op": "aggregate",
                "group_by": ["customer_id"],
                "aggregations": [
                    {"field": "amount", "func": "sum", "alias": "total_amount"},
                    {"field": "order_id", "func": "count", "alias": "n"},
                ],
            },
        ],
        "output_id": dst_id,
    }
    r = await client.post("/api/pipelines/step-schemas", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    schemas = payload["step_schemas"]
    # Filter preserves schema; aggregate collapses to group_by + aliases.
    assert "amount" in schemas["0"]
    assert "customer_id" in schemas["0"]
    assert set(schemas["1"]) == {"customer_id", "total_amount", "n"}
