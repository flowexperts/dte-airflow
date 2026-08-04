"""Scenarios for quality pipelines (pipeline_type="quality").

Covers the full HTTP stack: create → trigger → poll → quality results.
These are the tests that would have caught every 422 bug during development.
"""
from __future__ import annotations
import pytest
from tests.scenarios.helpers import create_source, create_pipeline, trigger_and_wait


@pytest.fixture
async def orders_source(client, scenario_ids, fixtures_dir):
    src_id = scenario_ids("source", "orders")
    await create_source(
        client,
        id=src_id, source_type="filesystem", connection_id="local_fs",
        config={"bucket_url": str(fixtures_dir), "file_glob": "orders.json"},
        table="orders",
    )
    return src_id


@pytest.mark.scenario
async def test_quality_pipeline_create_no_destination(client, scenario_ids, orders_source):
    """POST /api/pipelines with pipeline_type=quality and no output_id must return 200."""
    pipe_id = scenario_ids("pipeline")
    r = await client.post("/api/pipelines", json={
        "id": pipe_id,
        "name": pipe_id,
        "sources": [orders_source],
        "steps": [],
        "pipeline_type": "quality",
    })
    assert r.status_code in (200, 201), r.text


@pytest.mark.scenario
async def test_quality_pipeline_all_checks_pass(client, scenario_ids, fixtures_dir, orders_source):
    """All checks pass → run status 'completed', quality API returns results."""
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[orders_source],
        pipeline_type="quality",
        steps=[
            {"op": "check", "expr": "amount IS NOT NULL", "label": "amount not null", "severity": "fail"},
            {"op": "check", "expr": "amount > 0", "label": "amount positive", "severity": "fail"},
        ],
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed", run

    r = await client.get(f"/api/runs/{run['id']}/quality")
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert len(results) == 2
    assert all(res["passed"] for res in results)


@pytest.mark.scenario
async def test_quality_pipeline_hard_fail_downgrades_status(client, scenario_ids, orders_source):
    """A check with severity=fail that finds violations → run status 'failed_quality'."""
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[orders_source],
        pipeline_type="quality",
        steps=[
            {"op": "check", "expr": "amount > 9999", "label": "impossible", "severity": "fail"},
        ],
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "failed_quality", run

    r = await client.get(f"/api/runs/{run['id']}/quality")
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["passed"] is False
    assert results[0]["severity"] == "fail"


@pytest.mark.scenario
async def test_quality_pipeline_warn_check_gives_completed_with_warnings(client, scenario_ids, orders_source):
    """A failing check with severity=warn → 'completed_with_warnings', not 'failed_quality'."""
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[orders_source],
        pipeline_type="quality",
        steps=[
            {"op": "check", "expr": "amount > 9999", "label": "warn only", "severity": "warn"},
        ],
    )
    run = await trigger_and_wait(client, pipe_id)
    assert run["status"] == "completed_with_warnings", run

    results = (await client.get(f"/api/runs/{run['id']}/quality")).json()["results"]
    assert results[0]["passed"] is False
    assert results[0]["severity"] == "warn"


@pytest.mark.scenario
async def test_quality_pipeline_multiple_checks_run_independently(client, scenario_ids, orders_source):
    """A failing check does not prevent later checks from running."""
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[orders_source],
        pipeline_type="quality",
        steps=[
            {"op": "check", "expr": "amount > 9999", "label": "fails", "severity": "warn"},
            {"op": "check", "expr": "amount > 0", "label": "passes", "severity": "warn"},
        ],
    )
    run = await trigger_and_wait(client, pipe_id)
    results = (await client.get(f"/api/runs/{run['id']}/quality")).json()["results"]
    assert len(results) == 2
    passed = [r["passed"] for r in results]
    assert False in passed and True in passed


@pytest.mark.scenario
async def test_quality_pipeline_preview_returns_rows(client, scenario_ids, orders_source):
    """GET /api/pipelines/{id}/preview works for quality pipelines (no destination)."""
    pipe_id = scenario_ids("pipeline")
    await create_pipeline(
        client, id=pipe_id, sources=[orders_source],
        pipeline_type="quality",
        steps=[],
    )
    r = await client.get(f"/api/pipelines/{pipe_id}/preview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert len(body["rows"]) > 0


@pytest.mark.scenario
async def test_quality_pipeline_dry_run_returns_rows(client, scenario_ids, orders_source):
    """POST /api/pipelines/dry-run with pipeline_type=quality works."""
    r = await client.post("/api/pipelines/dry-run", json={
        "id": "dry_q",
        "name": "dry_q",
        "sources": [orders_source],
        "steps": [],
        "pipeline_type": "quality",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert len(body["rows"]) > 0
