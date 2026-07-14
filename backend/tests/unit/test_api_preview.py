import json
import pytest
import asyncio
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import (
    get_pipeline_store, get_source_store, get_destination_store,
)
from dte.store.memory import (
    MemoryPipelineStore, MemorySourceStore, MemoryDestinationStore,
)


def _pipeline_payload(pid, steps=None):
    return {
        "id": pid,
        "name": "prev",
        "sources": ["src"],
        "steps": steps or [],
        "output_id": "out1",
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(tmp_path):
    p_store = MemoryPipelineStore()
    s_store = MemorySourceStore()
    d_store = MemoryDestinationStore()
    app.dependency_overrides[get_pipeline_store] = lambda: p_store
    app.dependency_overrides[get_source_store] = lambda: s_store
    app.dependency_overrides[get_destination_store] = lambda: d_store
    _run(s_store.save({
        "id": "src", "source_type": "filesystem",
        "config": {"bucket_url": str(tmp_path), "file_glob": "input.json"},
        "table": "input",
    }))
    _run(d_store.save({
        "id": "out1", "config": {"type": "json_file", "path": str(tmp_path / "out.json")},
    }))
    yield TestClient(app), p_store
    app.dependency_overrides.clear()


def _save(store, payload):
    _run(store.save(payload))


def test_preview_returns_sample_rows(tmp_path, client):
    c, store = client
    data = [{"name": "alice", "age": 30}, {"name": "bob", "age": 25}]
    (tmp_path / "input.json").write_text(json.dumps(data))
    _save(store, _pipeline_payload("p1"))

    r = c.get("/api/pipelines/p1/preview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "rows" in body
    assert "count" in body
    assert body["count"] == len(body["rows"])
    assert body["count"] == 2


def test_preview_limit_respected(tmp_path, client):
    c, store = client
    data = [{"n": i} for i in range(50)]
    (tmp_path / "input.json").write_text(json.dumps(data))
    _save(store, _pipeline_payload("p2"))

    r = c.get("/api/pipelines/p2/preview?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) <= 5
    assert body["count"] == len(body["rows"])


def test_preview_invalid_pipeline_returns_404(client):
    c, _ = client
    r = c.get("/api/pipelines/nonexistent/preview")
    assert r.status_code == 404


def test_preview_bad_step_returns_422(tmp_path, client):
    c, store = client
    data = [{"x": 1}]
    (tmp_path / "input.json").write_text(json.dumps(data))
    _save(store, _pipeline_payload("p3", steps=[{"op": "filter", "expr": "this_column_does_not_exist > 0"}]))

    r = c.get("/api/pipelines/p3/preview")
    assert r.status_code == 422
