import asyncio
import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import get_run_store
from dte.store.memory import MemoryRunStore


@pytest.fixture
def client():
    r_store = MemoryRunStore()
    app.dependency_overrides[get_run_store] = lambda: r_store
    yield TestClient(app), r_store
    app.dependency_overrides.clear()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_list_runs_empty(client):
    c, _ = client
    r = c.get("/api/pipelines/p1/runs")
    assert r.status_code == 200
    assert r.json() == []


def test_list_runs_returns_own_pipeline_only(client):
    c, store = client
    _run(store.create("p1"))
    _run(store.create("p1"))
    _run(store.create("p2"))

    r = c.get("/api/pipelines/p1/runs")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert all(row["pipeline_id"] == "p1" for row in body)

    r = c.get("/api/pipelines/p2/runs")
    assert len(r.json()) == 1


def test_list_runs_limit(client):
    c, store = client
    for _ in range(5):
        _run(store.create("p1"))

    r = c.get("/api/pipelines/p1/runs?limit=3")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_run_has_started_at_on_create(client):
    c, store = client
    run_id = _run(store.create("p1"))

    r = c.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["started_at"] is not None
    assert body["finished_at"] is None


def test_run_finished_at_set_on_completion(client):
    c, store = client
    run_id = _run(store.create("p1"))
    _run(store.update(run_id, status="completed", rows_written=42))
    # simulate _execute_pipeline setting finished_at
    from datetime import datetime, timezone
    _run(store.update(run_id, finished_at=datetime.now(timezone.utc).isoformat()))

    r = c.get(f"/api/runs/{run_id}")
    body = r.json()
    assert body["status"] == "completed"
    assert body["finished_at"] is not None


def test_list_runs_includes_timestamps(client):
    c, store = client
    _run(store.create("p1"))
    r = c.get("/api/pipelines/p1/runs")
    body = r.json()
    assert "started_at" in body[0]
    assert "finished_at" in body[0]
