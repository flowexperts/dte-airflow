import asyncio
import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import get_lookup_table_store, get_pipeline_store
from dte.models.pipeline import Pipeline, LookupTableBase
from tests.fakes import FakeLookupTableStore, FakePipelineStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client():
    lt_store = FakeLookupTableStore()
    p_store = FakePipelineStore()
    app.dependency_overrides[get_lookup_table_store] = lambda: lt_store
    app.dependency_overrides[get_pipeline_store] = lambda: p_store
    yield TestClient(app), lt_store, p_store
    app.dependency_overrides.clear()


def _body(lid="l1", mappings=None, default=None, name=None):
    return {
        "id": lid,
        "name": name or f"{lid}-name",
        "mappings": mappings or {"US": "United States", "CA": "Canada"},
        "default": default,
    }


def _create(lid="l1", **kw) -> LookupTableBase:
    return LookupTableBase(**_body(lid=lid, **kw))


def test_create_lookup_201(client):
    c, lt_store, _ = client
    r = c.post("/api/lookup-tables", json=_body())
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "l1"
    got = _run(lt_store.get("l1"))
    assert got.mappings["US"] == "United States"


def test_create_duplicate_409(client):
    c, lt_store, _ = client
    _run(lt_store.save(_create()))
    r = c.post("/api/lookup-tables", json=_body())
    assert r.status_code == 409


def test_list_lookups(client):
    c, lt_store, _ = client
    _run(lt_store.save(_create("l1")))
    _run(lt_store.save(_create("l2")))
    r = c.get("/api/lookup-tables")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert ids == {"l1", "l2"}


def test_get_lookup(client):
    c, lt_store, _ = client
    _run(lt_store.save(_create("l1")))
    r = c.get("/api/lookup-tables/l1")
    assert r.status_code == 200
    assert r.json()["mappings"]["US"] == "United States"


def test_get_lookup_404(client):
    c, *_ = client
    r = c.get("/api/lookup-tables/nope")
    assert r.status_code == 404


def test_update_lookup(client):
    c, lt_store, _ = client
    _run(lt_store.save(_create("l1")))
    updated = _body("l1", mappings={"GB": "United Kingdom"}, default="Other")
    r = c.put("/api/lookup-tables/l1", json=updated)
    assert r.status_code == 200
    assert r.json()["mappings"] == {"GB": "United Kingdom"}
    assert r.json()["default"] == "Other"


def test_update_id_mismatch_400(client):
    c, lt_store, _ = client
    _run(lt_store.save(_create("l1")))
    r = c.put("/api/lookup-tables/l1", json=_body("other"))
    assert r.status_code == 400


def test_delete_204(client):
    c, lt_store, _ = client
    _run(lt_store.save(_create("l1")))
    r = c.delete("/api/lookup-tables/l1")
    assert r.status_code == 204
    assert _run(lt_store.get("l1")) is None


def test_delete_referenced_409(client):
    c, lt_store, p_store = client
    _run(lt_store.save(_create("l1")))
    _run(p_store.save(Pipeline(
        id="p1", name="p", sources=["s1"], steps=[
            {"op": "map", "mode": "lookup", "field": "cc", "lookup_id": "l1"},
        ], output_id="d1",
    )))
    r = c.delete("/api/lookup-tables/l1")
    assert r.status_code == 409
    assert r.json()["detail"]["referenced_by"] == ["p1"]


def test_bulk_delete_lookup_tables_mixed(client):
    c, lt_store, p_store = client
    _run(lt_store.save(_create("l1")))
    _run(lt_store.save(_create("l2")))
    _run(lt_store.save(_create("l3")))
    _run(p_store.save(Pipeline(
        id="p1", name="p", sources=["s1"], steps=[
            {"op": "map", "mode": "lookup", "field": "cc", "lookup_id": "l3"},
        ], output_id="d1",
    )))

    r = c.post("/api/lookup-tables/bulk-delete", json={"ids": ["l1", "l2", "l3", "ghost"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["deleted"]) == ["l1", "l2"]
    assert body["not_found"] == ["ghost"]
    assert body["blocked"] == [{"id": "l3", "referenced_by": ["p1"]}]


def test_bulk_delete_lookup_tables_empty_422(client):
    c, *_ = client
    r = c.post("/api/lookup-tables/bulk-delete", json={"ids": []})
    assert r.status_code == 422


# ── Editable name + server-generated id ───────────────────────────────────
def test_lookup_without_id_generates_uuid(client):
    c, *_ = client
    r = c.post("/api/lookup-tables", json={"name": "countries", "mappings": {"US": "USA"}})
    assert r.status_code == 201, r.text
    row = r.json()
    assert "-" in row["id"] and len(row["id"]) >= 32
    assert row["name"] == "countries"


def test_lookup_duplicate_name_409(client):
    c, *_ = client
    body = {"name": "countries", "mappings": {"US": "USA"}}
    r1 = c.post("/api/lookup-tables", json=body)
    assert r1.status_code == 201
    r2 = c.post("/api/lookup-tables", json=body)
    assert r2.status_code == 409, r2.text


def test_lookup_rename_by_stable_id(client):
    c, *_ = client
    r = c.post("/api/lookup-tables", json={"name": "old", "mappings": {}})
    assert r.status_code == 201
    lid = r.json()["id"]
    r2 = c.put(f"/api/lookup-tables/{lid}", json={"id": lid, "name": "new", "mappings": {}})
    assert r2.status_code == 200, r2.text
    assert r2.json()["name"] == "new"
