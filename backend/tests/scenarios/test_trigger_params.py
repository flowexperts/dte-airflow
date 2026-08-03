"""End-to-end coverage for trigger-time params + system-variable interpolation."""
from __future__ import annotations

import asyncio
import json
from datetime import date

from tests.scenarios.helpers import (
    create_destination,
    create_source,
    read_output_file,
)


async def _seed(client, scenario_ids, fixtures_dir, out_dir, out_name):
    src_id = scenario_ids("source", "orders")
    dst_id = scenario_ids("destination", "out")
    out_path = out_dir / out_name
    await create_source(
        client,
        id=src_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"},
        table="orders",
    )
    await create_destination(
        client,
        id=dst_id, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )
    return src_id, dst_id, out_path


async def _create_pipeline_with_params(
    client, *, id, sources, steps, output_id, params,
):
    payload = {
        "id": id, "name": id,
        "sources": sources, "steps": steps, "output_id": output_id,
        "params": params,
    }
    r = await client.post("/api/pipelines", json=payload)
    assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text}"
    return r.json()


async def _trigger_and_wait(client, pipeline_id, *, params=None, timeout=15.0):
    body = {"params": params} if params else {}
    r = await client.post(f"/api/pipelines/{pipeline_id}/trigger", json=body)
    assert r.status_code == 200, f"trigger failed: {r.status_code} {r.text}"
    run_id = r.json()["run_id"]
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    run: dict = {}
    while loop.time() < deadline:
        r = await client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200, r.text
        run = r.json()
        if run["status"] in ("completed", "failed"):
            return run
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish (last: {run})")


async def test_pipeline_params_persist_across_create_edit_get(
    client, scenario_ids, fixtures_dir, out_dir
):
    """Regression: PUT on a pipeline used to drop params from the on_conflict
    SET clause. Reload after edit must return the added inputs."""
    src_id, dst_id, _ = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "params_persist.json",
    )
    pipe_id = scenario_ids("pipeline")
    await _create_pipeline_with_params(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "amount > {{params.min}}"}],
        output_id=dst_id,
        params=[{"name": "min", "type": "int", "required": True}],
    )
    # Reload immediately — INSERT path must have persisted the declaration.
    r = await client.get(f"/api/pipelines/{pipe_id}")
    assert r.status_code == 200
    got = r.json()
    assert [p["name"] for p in got.get("params", [])] == ["min"]

    # Edit to add a second param → PUT hits on_conflict_do_update path.
    got["params"].append({
        "name": "start_date", "type": "date", "required": False, "default": "2024-01-01",
    })
    r = await client.put(f"/api/pipelines/{pipe_id}", json=got)
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/pipelines/{pipe_id}")
    names = {p["name"] for p in r.json().get("params", [])}
    assert names == {"min", "start_date"}


async def test_trigger_with_params_filters_by_placeholder(
    client, scenario_ids, fixtures_dir, out_dir
):
    """A filter step using {{params.min}} should filter by the value passed
    at trigger time, and the run record should carry that value back."""
    src_id, dst_id, out_path = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "params_min.json",
    )
    pipe_id = scenario_ids("pipeline")
    await _create_pipeline_with_params(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "amount > {{params.min}}"}],
        output_id=dst_id,
        params=[{"name": "min", "type": "int", "required": True}],
    )
    run = await _trigger_and_wait(client, pipe_id, params={"min": "100"})
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    assert {r["order_id"] for r in rows} == {
        "o02", "o04", "o05", "o07", "o09", "o13", "o14", "o16", "o18",
    }
    # Same pipeline, different threshold — output file is overwritten.
    run2 = await _trigger_and_wait(client, pipe_id, params={"min": "250"})
    assert run2["status"] == "completed"
    rows2 = read_output_file(out_path)
    assert {r["order_id"] for r in rows2} == {"o04", "o09", "o18"}
    # run record carries the caller-supplied params + system vars
    assert run2["params"]["params"] == {"min": "250"}
    assert run2["params"]["today"] == date.today().isoformat()


async def test_trigger_with_system_variable_today(
    client, scenario_ids, fixtures_dir, out_dir
):
    src_id, dst_id, out_path = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "params_today.json",
    )
    pipe_id = scenario_ids("pipeline")
    # Every fixture row has ordered_at in 2024 — well before today — so a
    # filter of "ordered_at < today" should keep all 20. System vars work
    # without a declared params list.
    await _create_pipeline_with_params(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "ordered_at < '{{today}}'"}],
        output_id=dst_id,
        params=[],
    )
    run = await _trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    assert len(rows) == 20


async def test_trigger_with_dynamic_param_sentinel(
    client, scenario_ids, fixtures_dir, out_dir
):
    """A declared date param bound to `{{today}}` at trigger time should
    resolve to today's ISO date before the filter runs."""
    src_id, dst_id, out_path = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "params_dynamic.json",
    )
    pipe_id = scenario_ids("pipeline")
    await _create_pipeline_with_params(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "ordered_at < '{{params.as_of}}'"}],
        output_id=dst_id,
        params=[{"name": "as_of", "type": "date", "required": True}],
    )
    run = await _trigger_and_wait(
        client, pipe_id, params={"as_of": "{{today}}"},
    )
    assert run["status"] == "completed", run
    rows = read_output_file(out_path)
    # Fixture rows all in 2024 → all 20 pass a "< today" filter.
    assert len(rows) == 20
    # The persisted run context carries the *resolved* date, not the sentinel.
    assert run["params"]["params"]["as_of"] == date.today().isoformat()


async def test_save_rejects_undeclared_param_reference(
    client, scenario_ids, fixtures_dir, out_dir
):
    src_id, dst_id, _ = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "params_bad.json",
    )
    pipe_id = scenario_ids("pipeline")
    r = await client.post(
        "/api/pipelines",
        json={
            "id": pipe_id, "name": pipe_id,
            "sources": [src_id],
            "steps": [{"op": "filter", "expr": "amount > {{params.missing}}"}],
            "output_id": dst_id,
            "params": [],
        },
    )
    assert r.status_code == 422, r.text
    assert "missing" in r.text


async def test_trigger_missing_required_param_returns_422(
    client, scenario_ids, fixtures_dir, out_dir
):
    src_id, dst_id, _ = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "params_req.json",
    )
    pipe_id = scenario_ids("pipeline")
    await _create_pipeline_with_params(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "amount > {{params.min}}"}],
        output_id=dst_id,
        params=[{"name": "min", "type": "int", "required": True}],
    )
    r = await client.post(f"/api/pipelines/{pipe_id}/trigger", json={"params": {}})
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["code"] == "param_validation_error"
    assert body["detail"]["param"] == "min"


async def test_trigger_type_mismatch_returns_422(
    client, scenario_ids, fixtures_dir, out_dir
):
    src_id, dst_id, _ = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "params_type.json",
    )
    pipe_id = scenario_ids("pipeline")
    await _create_pipeline_with_params(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "amount > {{params.min}}"}],
        output_id=dst_id,
        params=[{"name": "min", "type": "int", "required": True}],
    )
    r = await client.post(
        f"/api/pipelines/{pipe_id}/trigger",
        json={"params": {"min": "not-an-int"}},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["code"] == "param_validation_error"
    assert body["detail"]["expected_type"] == "int"


async def test_preview_endpoint_accepts_params_query(
    client, scenario_ids, fixtures_dir, out_dir
):
    src_id, dst_id, _ = await _seed(
        client, scenario_ids, fixtures_dir, out_dir, "params_preview.json",
    )
    pipe_id = scenario_ids("pipeline")
    await _create_pipeline_with_params(
        client, id=pipe_id, sources=[src_id],
        steps=[{"op": "filter", "expr": "amount > {{params.min}}"}],
        output_id=dst_id,
        params=[{"name": "min", "type": "int", "required": True}],
    )
    encoded = json.dumps({"min": "200"})
    r = await client.get(
        f"/api/pipelines/{pipe_id}/preview",
        params={"limit": 20, "params": encoded},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("error") is None, body
    got = {row["order_id"] for row in body["rows"]}
    # amounts > 200: o04=300, o09=500, o14=250, o18=400
    assert got == {"o04", "o09", "o14", "o18"}
