import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import get_source_store, get_pipeline_store
from dte.models.pipeline import Pipeline, SourceCreate
from tests.fakes import FakeSourceStore, FakePipelineStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client():
    s_store = FakeSourceStore()
    p_store = FakePipelineStore()
    app.dependency_overrides[get_source_store] = lambda: s_store
    app.dependency_overrides[get_pipeline_store] = lambda: p_store
    yield TestClient(app), s_store, p_store
    app.dependency_overrides.clear()


def _src(sid="s1", table="dummy", connection_id="local_fs"):
    return {
        "id": sid, "connection_id": connection_id,
        "source_type": "filesystem",
        "config": {"bucket_url": "/tmp"}, "table": table,
    }


def _src_create(sid="s1", table="dummy", connection_id="local_fs"):
    return SourceCreate(
        id=sid, connection_id=connection_id,
        source_type="filesystem",
        config={"bucket_url": "/tmp"}, table=table,
    )


def test_create_source_201(client):
    c, s_store, _ = client
    r = c.post("/api/sources", json=_src())
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "s1"
    assert _run(s_store.get("s1")).table == "dummy"


def test_create_source_duplicate_409(client):
    c, s_store, _ = client
    _run(s_store.save(_src_create()))
    r = c.post("/api/sources", json=_src())
    assert r.status_code == 409


def test_list_sources(client):
    c, s_store, _ = client
    _run(s_store.save(_src_create("s1")))
    _run(s_store.save(_src_create("s2")))
    r = c.get("/api/sources")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert ids == {"s1", "s2"}


def test_get_source(client):
    c, s_store, _ = client
    _run(s_store.save(_src("s1")))
    r = c.get("/api/sources/s1")
    assert r.status_code == 200
    assert r.json()["id"] == "s1"


def test_get_source_404(client):
    c, *_ = client
    r = c.get("/api/sources/nope")
    assert r.status_code == 404


def test_update_source(client):
    c, s_store, _ = client
    _run(s_store.save(_src("s1")))
    updated = _src("s1", table="renamed")
    r = c.put("/api/sources/s1", json=updated)
    assert r.status_code == 200
    assert r.json()["table"] == "renamed"


def test_update_source_id_mismatch_400(client):
    c, s_store, _ = client
    _run(s_store.save(_src("s1")))
    r = c.put("/api/sources/s1", json=_src("other"))
    assert r.status_code == 400


def test_delete_source_204(client):
    c, s_store, _ = client
    _run(s_store.save(_src("s1")))
    r = c.delete("/api/sources/s1")
    assert r.status_code == 204
    assert _run(s_store.get("s1")) is None


def test_delete_source_referenced_409(client):
    c, s_store, p_store = client
    _run(s_store.save(_src("s1")))
    _run(p_store.save(Pipeline(
        id="p1", name="p", sources=["s1"], steps=[], output_id="d1",
    )))
    r = c.delete("/api/sources/s1")
    assert r.status_code == 409
    assert r.json()["detail"]["referenced_by"] == ["p1"]


def test_source_schema_by_id(tmp_path, client):
    c, s_store, _ = client
    data = [{"user_id": 1, "name": "alice"}]
    (tmp_path / "u.json").write_text(json.dumps(data))
    _run(s_store.save({
        "id": "s1", "connection_id": "local_fs",
        "source_type": "filesystem",
        "config": {"bucket_url": str(tmp_path), "file_glob": "u.json"},
        "table": "users",
    }))
    r = c.get("/api/sources/s1/schema")
    assert r.status_code == 200, r.text
    names = {f["name"] for f in r.json()["fields"]}
    assert {"user_id", "name"}.issubset(names)


def test_source_schema_by_id_404(client):
    c, *_ = client
    r = c.get("/api/sources/nope/schema")
    assert r.status_code == 404
