import asyncio
import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import get_pipeline_store, get_run_store
from dte.store.memory import MemoryPipelineStore, MemoryRunStore


@pytest.fixture
def client():
    p_store = MemoryPipelineStore()
    r_store = MemoryRunStore()
    app.dependency_overrides[get_pipeline_store] = lambda: p_store
    app.dependency_overrides[get_run_store] = lambda: r_store
    yield TestClient(app), p_store, r_store
    app.dependency_overrides.clear()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _pipeline(pipeline_id: str = "p1", name: str = "orig"):
    return {
        "id": pipeline_id,
        "name": name,
        "sources": [],
        "steps": [],
        "output": {"type": "json_file", "path": "/tmp/out.json"},
    }


def test_update_pipeline_replaces_definition(client):
    c, p_store, _ = client
    _run(p_store.save(_pipeline("p1", "orig")))

    updated = _pipeline("p1", "renamed")
    r = c.put("/api/pipelines/p1", json=updated)

    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert _run(p_store.get("p1"))["name"] == "renamed"


def test_update_missing_pipeline_returns_404(client):
    c, _, _ = client
    r = c.put("/api/pipelines/nope", json=_pipeline("nope"))
    assert r.status_code == 404


def test_update_pipeline_id_mismatch_returns_400(client):
    c, p_store, _ = client
    _run(p_store.save(_pipeline("p1")))
    body = _pipeline("different-id")
    r = c.put("/api/pipelines/p1", json=body)
    assert r.status_code == 400


def test_delete_pipeline_returns_204(client):
    c, p_store, _ = client
    _run(p_store.save(_pipeline("p1")))
    r = c.delete("/api/pipelines/p1")
    assert r.status_code == 204
    assert _run(p_store.get("p1")) is None


def test_delete_missing_pipeline_returns_404(client):
    c, _, _ = client
    r = c.delete("/api/pipelines/nope")
    assert r.status_code == 404


def test_delete_cascades_runs(client):
    c, p_store, r_store = client
    _run(p_store.save(_pipeline("p1")))
    _run(p_store.save(_pipeline("p2")))
    _run(r_store.create("p1"))
    _run(r_store.create("p1"))
    keep = _run(r_store.create("p2"))

    r = c.delete("/api/pipelines/p1")
    assert r.status_code == 204

    assert _run(r_store.list_for_pipeline("p1")) == []
    remaining = _run(r_store.list_for_pipeline("p2"))
    assert [x["id"] for x in remaining] == [keep]
