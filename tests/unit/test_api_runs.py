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
