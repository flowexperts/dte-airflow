import asyncio
import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import get_destination_store, get_pipeline_store
from dte.models.pipeline import Pipeline
from tests.fakes import FakeDestinationStore, FakePipelineStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client():
    d_store = FakeDestinationStore()
    p_store = FakePipelineStore()
    app.dependency_overrides[get_destination_store] = lambda: d_store
    app.dependency_overrides[get_pipeline_store] = lambda: p_store
    yield TestClient(app), d_store, p_store
    app.dependency_overrides.clear()


def _dest(did="d1", path="/tmp/out.json", connection_id="local_fs"):
    return {"id": did, "connection_id": connection_id,
            "config": {"type": "json_file", "path": path}}


def test_create_destination_201(client):
    c, d_store, _ = client
    r = c.post("/api/destinations", json=_dest())
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "d1"
    assert _run(d_store.get("d1"))["config"]["type"] == "json_file"


def test_create_destination_duplicate_409(client):
    c, d_store, _ = client
    _run(d_store.save(_dest()))
    r = c.post("/api/destinations", json=_dest())
    assert r.status_code == 409


def test_list_destinations(client):
    c, d_store, _ = client
    _run(d_store.save(_dest("d1")))
    _run(d_store.save(_dest("d2")))
    r = c.get("/api/destinations")
    ids = {row["id"] for row in r.json()}
    assert ids == {"d1", "d2"}


def test_get_destination(client):
    c, d_store, _ = client
    _run(d_store.save(_dest("d1")))
    r = c.get("/api/destinations/d1")
    assert r.status_code == 200
    assert r.json()["id"] == "d1"


def test_get_destination_404(client):
    c, *_ = client
    r = c.get("/api/destinations/nope")
    assert r.status_code == 404


def test_update_destination(client):
    c, d_store, _ = client
    _run(d_store.save(_dest("d1")))
    r = c.put("/api/destinations/d1", json=_dest("d1", "/tmp/new.json"))
    assert r.status_code == 200
    assert r.json()["config"]["path"] == "/tmp/new.json"


def test_delete_destination_204(client):
    c, d_store, _ = client
    _run(d_store.save(_dest("d1")))
    r = c.delete("/api/destinations/d1")
    assert r.status_code == 204
    assert _run(d_store.get("d1")) is None


def test_delete_destination_referenced_409(client):
    c, d_store, p_store = client
    _run(d_store.save(_dest("d1")))
    _run(p_store.save(Pipeline(
        id="p1", name="p", sources=["s1"], steps=[], output_id="d1",
    )))
    r = c.delete("/api/destinations/d1")
    assert r.status_code == 409
    assert r.json()["detail"]["referenced_by"] == ["p1"]
