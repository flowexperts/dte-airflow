import asyncio
import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import (
    get_pipeline_store, get_run_store,
    get_source_store, get_destination_store,
)
from dte.models.pipeline import Pipeline, SourceCreate, DestinationCreate
from tests.fakes import (
    FakePipelineStore, FakeRunStore,
    FakeSourceStore, FakeDestinationStore,
)


@pytest.fixture
def client():
    p_store = FakePipelineStore()
    r_store = FakeRunStore()
    s_store = FakeSourceStore()
    d_store = FakeDestinationStore()
    app.dependency_overrides[get_pipeline_store] = lambda: p_store
    app.dependency_overrides[get_run_store] = lambda: r_store
    app.dependency_overrides[get_source_store] = lambda: s_store
    app.dependency_overrides[get_destination_store] = lambda: d_store
    # Seed a default source + destination so most tests just work.
    _run(s_store.save(SourceCreate(
        id="s1", connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": "/tmp"}, table="dummy",
    )))
    _run(d_store.save(DestinationCreate(
        id="out1", connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/out.json"},
    )))
    yield TestClient(app), p_store, r_store, s_store, d_store
    app.dependency_overrides.clear()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _pipeline(pipeline_id: str = "p1", name: str = "orig", sources=("s1",), output_id="out1"):
    return {
        "id": pipeline_id,
        "name": name,
        "sources": list(sources),
        "steps": [],
        "output_id": output_id,
    }


def _obj(**kwargs) -> Pipeline:
    return Pipeline(**_pipeline(**kwargs))


def test_create_pipeline_with_valid_refs(client):
    c, p_store, _, _, _ = client
    r = c.post("/api/pipelines", json=_pipeline())
    assert r.status_code == 200, r.text
    assert _run(p_store.get("p1")).name == "orig"


def test_create_pipeline_missing_source_returns_422(client):
    c, _, _, _, _ = client
    body = _pipeline(sources=("does-not-exist",))
    r = c.post("/api/pipelines", json=body)
    assert r.status_code == 422
    assert "does-not-exist" in r.json()["detail"].get("missing_sources", [])


def test_create_pipeline_missing_destination_returns_422(client):
    c, _, _, _, _ = client
    body = _pipeline(output_id="nope")
    r = c.post("/api/pipelines", json=body)
    assert r.status_code == 422
    assert r.json()["detail"].get("missing_destination") == "nope"


def test_update_pipeline_replaces_definition(client):
    c, p_store, _, _, _ = client
    _run(p_store.save(_obj(pipeline_id="p1", name="orig")))

    updated = _pipeline("p1", "renamed")
    r = c.put("/api/pipelines/p1", json=updated)

    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert _run(p_store.get("p1")).name == "renamed"


def test_update_missing_pipeline_returns_404(client):
    c, _, _, _, _ = client
    r = c.put("/api/pipelines/nope", json=_pipeline("nope"))
    assert r.status_code == 404


def test_update_pipeline_id_mismatch_returns_400(client):
    c, p_store, _, _, _ = client
    _run(p_store.save(_obj(pipeline_id="p1")))
    body = _pipeline("different-id")
    r = c.put("/api/pipelines/p1", json=body)
    assert r.status_code == 400


def test_delete_pipeline_returns_204(client):
    c, p_store, _, _, _ = client
    _run(p_store.save(_obj(pipeline_id="p1")))
    r = c.delete("/api/pipelines/p1")
    assert r.status_code == 204
    assert _run(p_store.get("p1")) is None


def test_delete_missing_pipeline_returns_404(client):
    c, _, _, _, _ = client
    r = c.delete("/api/pipelines/nope")
    assert r.status_code == 404


def test_delete_cascades_runs(client):
    c, p_store, r_store, _, _ = client
    _run(p_store.save(_obj(pipeline_id="p1")))
    _run(p_store.save(_obj(pipeline_id="p2")))
    _run(r_store.create("p1"))
    _run(r_store.create("p1"))
    keep = _run(r_store.create("p2"))

    r = c.delete("/api/pipelines/p1")
    assert r.status_code == 204

    assert _run(r_store.list_for_pipeline("p1")) == []
    remaining = _run(r_store.list_for_pipeline("p2"))
    assert [x["id"] for x in remaining] == [keep]
