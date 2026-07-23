"""End-to-end coverage for GET /api/runs/{id}/events."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _run(coro):
    # Fresh loop per call — the autouse async fixtures may have already closed
    # the ambient loop by the time these sync tests execute.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_events_404_for_unknown_run(client):
    r = client.get("/api/runs/no-such-run/events")
    assert r.status_code == 404


def test_events_empty_for_pending_run(client, fake_stores):
    run_id = _run(fake_stores["run"].create("p1"))
    r = client.get(f"/api/runs/{run_id}/events")
    assert r.status_code == 200
    body = r.json()
    assert body == {"events": [], "count": 0}


def test_events_reflect_recorded_step_transitions(client, fake_stores):
    run_id = _run(fake_stores["run"].create("p1"))
    re = fake_stores["run_event"]
    _run(re.record(run_id, 0, "filter", "started"))
    _run(re.record(run_id, 0, "filter", "completed"))
    _run(re.record(run_id, 1, "rename", "started"))
    _run(re.record(run_id, 1, "rename", "failed", "boom"))

    body = client.get(f"/api/runs/{run_id}/events").json()
    assert body["count"] == 2
    step_by_idx = {e["step_index"]: e for e in body["events"]}
    assert step_by_idx[0]["op"] == "filter"
    assert step_by_idx[0]["status"] == "completed"
    assert step_by_idx[0]["finished_at"] is not None
    assert step_by_idx[1]["status"] == "failed"
    assert step_by_idx[1]["message"] == "boom"
