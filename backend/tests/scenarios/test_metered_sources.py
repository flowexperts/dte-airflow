"""Metered sources over the HTTP API (plan 093).

A `bigquery` connection whose "warehouse" is a DuckDB file: previews read a
cached sample, live preview and runs read the table, trigger asks for
confirmation with an estimate first. No real BigQuery anywhere.
"""
from __future__ import annotations

import ibis
import pyarrow as pa
import pytest

from dte.sources import metered
from tests.scenarios.helpers import (
    create_connection,
    create_destination,
    create_pipeline,
    create_source,
    read_output_file,
    trigger_and_wait,
)


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    """5 rows live; the sample is 2 rows, so every response says which it read."""
    db = tmp_path / "wh.duckdb"
    con = ibis.duckdb.connect(str(db))
    con.con.execute("CREATE TABLE events AS SELECT range AS n, range AS ts FROM range(5)")
    con.disconnect()

    calls = {"fetch": 0, "estimate": []}

    def fake_fetch(backend, kind, schema, table, n):
        calls["fetch"] += 1
        return pa.table({"n": [100, 101], "ts": [0, 1]})

    def fake_estimate(backend, kind, sql):
        calls["estimate"].append(sql)
        return 3 * 2**40

    monkeypatch.setattr("dte.engine.backend_registry._OPENERS",
                        {"bigquery": lambda creds: ibis.duckdb.connect(str(db))})
    monkeypatch.setattr(metered, "fetch_sample", fake_fetch)
    monkeypatch.setattr(metered, "estimate_bytes", fake_estimate)
    monkeypatch.setattr(metered, "partition_columns", lambda *a: ["ts"])
    return calls


async def _seed(client, scenario_ids, out_dir, steps=None):
    conn_id = scenario_ids("connection", "bq")
    await create_connection(client, id=conn_id, connection_type="bigquery",
                            credentials={"url": "bigquery://prj", "max_bytes_billed": 2**50})
    src = scenario_ids("source", "wh")
    await create_source(client, id=src, source_type="sql_database", connection_id=conn_id,
                        config={}, table="wh")
    dst = scenario_ids("destination", "out")
    out = out_dir / "events.json"
    await create_destination(client, id=dst, connection_id="local_fs",
                             config={"type": "json_file", "path": str(out)})
    pid = scenario_ids("pipeline")
    await create_pipeline(client, id=pid, sources=[{"source_id": src, "alias": "events", "table": "events"}],
                          steps=steps or [], output_id=dst)
    return src, pid, out


async def test_preview_reads_the_sample_and_says_so(client, scenario_ids, out_dir, warehouse):
    _, pid, _ = await _seed(client, scenario_ids, out_dir)
    for _ in range(2):
        body = (await client.get(f"/api/pipelines/{pid}/preview?limit=20")).json()
        assert body["error"] is None
        assert [r["n"] for r in body["rows"]] == [100, 101]
    assert warehouse["fetch"] == 1
    (s,) = body["samples"]
    assert s["alias"] == "events" and s["rows"] == 2 and s["taken_at"]


async def test_live_preview_reads_the_table(client, scenario_ids, out_dir, warehouse):
    _, pid, _ = await _seed(client, scenario_ids, out_dir)
    body = (await client.get(f"/api/pipelines/{pid}/preview?limit=20&live=true&confirm=true")).json()
    assert body["error"] is None
    assert sorted(r["n"] for r in body["rows"]) == [0, 1, 2, 3, 4]
    assert body["samples"] == []
    assert warehouse["fetch"] == 0


async def test_live_preview_without_confirm_only_estimates(client, scenario_ids, out_dir, warehouse):
    """The server, not the UI, gates the billed query: no confirm → estimate, no rows."""
    _, pid, _ = await _seed(client, scenario_ids, out_dir)
    pipeline = (await client.get(f"/api/pipelines/{pid}")).json()
    for r in (await client.get(f"/api/pipelines/{pid}/preview?limit=20&live=true"),
              await client.post("/api/pipelines/dry-run?limit=20&live=true", json=pipeline)):
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rows"] == [] and body["error"] is None
        assert body["estimate"]["bytes"] == 3 * 2**40 and body["estimate"]["engine"] == "bigquery"
    # Unmetered work is untouched: a sample preview needs no confirm and carries no estimate.
    body = (await client.get(f"/api/pipelines/{pid}/preview?limit=20")).json()
    assert body["rows"] and body.get("estimate") is None


async def test_refresh_drops_the_sample(client, scenario_ids, out_dir, warehouse):
    src, pid, _ = await _seed(client, scenario_ids, out_dir)
    await client.get(f"/api/pipelines/{pid}/preview")
    r = await client.delete(f"/api/sources/{src}/sample?table=events")
    assert r.status_code == 200 and r.json() == {"dropped": True}
    await client.get(f"/api/pipelines/{pid}/preview")
    assert warehouse["fetch"] == 2


async def test_trigger_estimates_then_runs_live_on_confirm(client, scenario_ids, out_dir, warehouse):
    _, pid, out = await _seed(client, scenario_ids, out_dir, steps=[{"op": "filter", "expr": "n > 1"}])
    r = await client.post(f"/api/pipelines/{pid}/trigger", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["enqueued"] is False and "run_id" not in body
    est = body["estimate"]
    assert est["bytes"] == 3 * 2**40
    assert est["est_cost_usd"] == pytest.approx(18.75)
    assert est["engine"] == "bigquery"
    assert est["max_bytes_billed"] == 2**50 and est["exceeds_cap"] is False
    # The compiled query (with its filter) is what got priced.
    assert len(warehouse["estimate"]) == 1 and "WHERE" in warehouse["estimate"][0].upper()

    run = await trigger_and_wait(client, pid, confirm=True)
    assert run["status"] == "completed", run
    assert sorted(r["n"] for r in read_output_file(out)) == [2, 3, 4]
    assert warehouse["fetch"] == 0  # runs never touch the sample


async def test_estimate_endpoint_prices_an_unsaved_body(client, scenario_ids, out_dir, warehouse):
    _, pid, _ = await _seed(client, scenario_ids, out_dir)
    pipeline = (await client.get(f"/api/pipelines/{pid}")).json()
    r = await client.post("/api/pipelines/estimate", json=pipeline)
    assert r.status_code == 200, r.text
    assert r.json()["metered"] is True and r.json()["bytes"] == 3 * 2**40


async def test_unmetered_pipeline_triggers_without_confirm(client, scenario_ids, fixtures_dir, out_dir):
    src = scenario_ids("source", "orders")
    await create_source(client, id=src, source_type="filesystem", connection_id="local_fs",
                        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"}, table="orders")
    dst = scenario_ids("destination", "out")
    await create_destination(client, id=dst, connection_id="local_fs",
                             config={"type": "json_file", "path": str(out_dir / "o.json")})
    pid = scenario_ids("pipeline")
    await create_pipeline(client, id=pid, sources=[src], steps=[], output_id=dst)
    assert (await trigger_and_wait(client, pid))["status"] == "completed"
    r = await client.post("/api/pipelines/estimate",
                          json=(await client.get(f"/api/pipelines/{pid}")).json())
    assert r.json()["metered"] is False


async def test_schema_reports_partition_columns(client, scenario_ids, out_dir, warehouse):
    src, _, _ = await _seed(client, scenario_ids, out_dir)
    body = (await client.get(f"/api/sources/{src}/schema?table=events")).json()
    assert [f["name"] for f in body["fields"]] == ["n", "ts"]
    assert body["partition_columns"] == ["ts"]
