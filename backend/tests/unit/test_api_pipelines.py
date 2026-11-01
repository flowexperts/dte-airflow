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


def _pipeline(pipeline_id: str = "p1", name: str | None = None, sources=("s1",), output_id="out1"):
    # Default name derives from id so tests that seed multiple pipelines get
    # distinct names (UNIQUE(name) is enforced by the fake store).
    return {
        "id": pipeline_id,
        "name": name if name is not None else pipeline_id,
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
    assert _run(p_store.get("p1")).name == "p1"


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


# ── Editable name + server-generated id ───────────────────────────────────
def test_pipeline_without_id_generates_uuid(client):
    c, p_store, _, _, _ = client
    body = {
        "name": "brand new",
        "sources": ["s1"],
        "steps": [],
        "output_id": "out1",
    }
    r = c.post("/api/pipelines", json=body)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert "-" in pid and len(pid) >= 32
    row = _run(p_store.get(pid))
    assert row is not None and row.name == "brand new"


def test_pipeline_duplicate_name_409(client):
    c, _p, _r, _s, _d = client
    body = {"name": "shared", "sources": ["s1"], "steps": [], "output_id": "out1"}
    r1 = c.post("/api/pipelines", json=body)
    assert r1.status_code == 200
    r2 = c.post("/api/pipelines", json=body)
    assert r2.status_code == 409, r2.text


def test_pipeline_rename_by_stable_id(client):
    c, _p, _r, _s, _d = client
    r = c.post("/api/pipelines", json={
        "name": "old", "sources": ["s1"], "steps": [], "output_id": "out1",
    })
    assert r.status_code == 200
    pid = r.json()["id"]
    r2 = c.put(f"/api/pipelines/{pid}", json={
        "id": pid, "name": "new", "sources": ["s1"], "steps": [], "output_id": "out1",
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["name"] == "new"


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


def test_bulk_delete_pipelines_mixed(client):
    c, p_store, r_store, _, _ = client
    _run(p_store.save(_obj(pipeline_id="p1")))
    _run(p_store.save(_obj(pipeline_id="p2")))
    _run(r_store.create("p1"))

    r = c.post("/api/pipelines/bulk-delete", json={"ids": ["p1", "p2", "ghost"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["deleted"]) == ["p1", "p2"]
    assert body["not_found"] == ["ghost"]
    assert body["blocked"] == []
    assert _run(r_store.list_for_pipeline("p1")) == []


def test_bulk_delete_pipelines_empty_422(client):
    c, *_ = client
    r = c.post("/api/pipelines/bulk-delete", json={"ids": []})
    assert r.status_code == 422


# ─── SourceTableRef validation (plan 056) ──────────────────────────────────


def _seed_sql_source(s_store, sid="pgsrc"):
    _run(s_store.save(SourceCreate(
        id=sid, connection_id="local_fs", source_type="sql_database",
        config={}, table=sid,
    )))


def test_create_pipeline_accepts_bare_source_ids_as_shorthand(client):
    """`sources: ["s1"]` keeps working — the alias defaults to the id."""
    c, p_store, _, _, _ = client
    r = c.post("/api/pipelines", json=_pipeline())
    assert r.status_code == 200, r.text
    saved = _run(p_store.get("p1"))
    assert saved.sources[0]["source_id"] == "s1"
    assert saved.sources[0]["alias"] == "s1"


def test_create_pipeline_duplicate_alias_returns_422(client):
    c, _, _, s_store, _ = client
    _seed_sql_source(s_store, "pgsrc")
    body = _pipeline()
    body["sources"] = [
        {"source_id": "pgsrc", "alias": "t1", "table": "orders"},
        {"source_id": "pgsrc", "alias": "t1", "table": "customers"},
    ]
    r = c.post("/api/pipelines", json=body)
    assert r.status_code == 422, r.text
    assert "t1" in r.json()["detail"]["duplicate_aliases"]


def test_create_pipeline_sql_database_ref_without_table_returns_422(client):
    c, _, _, s_store, _ = client
    _seed_sql_source(s_store, "pgsrc")
    body = _pipeline()
    body["sources"] = [{"source_id": "pgsrc", "alias": "t1"}]
    r = c.post("/api/pipelines", json=body)
    assert r.status_code == 422, r.text
    assert "table" in r.json()["detail"]["table_errors"][0]


def test_create_pipeline_non_sql_database_ref_with_table_returns_422(client):
    c, _, _, s_store, _ = client
    # s1 is a filesystem source (seeded by the fixture).
    body = _pipeline()
    body["sources"] = [{"source_id": "s1", "alias": "s1", "table": "unexpected"}]
    r = c.post("/api/pipelines", json=body)
    assert r.status_code == 422, r.text
    assert "table" in r.json()["detail"]["table_errors"][0]


def test_create_pipeline_two_tables_from_one_source(client):
    """The point of the feature: one sql_database source, two aliases,
    two different tables."""
    c, p_store, _, s_store, _ = client
    _seed_sql_source(s_store, "pgsrc")
    body = _pipeline()
    body["sources"] = [
        {"source_id": "pgsrc", "alias": "orders_t", "table": "orders"},
        {"source_id": "pgsrc", "alias": "customers_t", "table": "customers"},
    ]
    r = c.post("/api/pipelines", json=body)
    assert r.status_code == 200, r.text
    saved = _run(p_store.get("p1"))
    aliases = {s["alias"]: s["table"] for s in saved.sources}
    assert aliases == {"orders_t": "orders", "customers_t": "customers"}


def test_create_pipeline_join_operand_unknown_alias_returns_422(client):
    c, _, _, s_store, _ = client
    _seed_sql_source(s_store, "pgsrc")
    body = _pipeline()
    body["sources"] = [
        {"source_id": "pgsrc", "alias": "orders_t", "table": "orders"},
        {"source_id": "pgsrc", "alias": "customers_t", "table": "customers"},
    ]
    body["steps"] = [{
        "op": "join",
        "left": "orders_t",
        "right": "does_not_exist",
        "on": "id",
        "how": "inner",
        "output_id": "joined",
    }]
    r = c.post("/api/pipelines", json=body)
    assert r.status_code == 422, r.text
    join_errors = r.json()["detail"]["join_errors"]
    assert any("does_not_exist" in e for e in join_errors)


def test_create_pipeline_join_operand_resolves_to_earlier_step_output(client):
    """A join's left/right may name an earlier step's output_id, not just
    a declared source alias."""
    c, p_store, _, s_store, _ = client
    _seed_sql_source(s_store, "pgsrc")
    body = _pipeline()
    body["sources"] = [
        {"source_id": "pgsrc", "alias": "a", "table": "orders"},
        {"source_id": "pgsrc", "alias": "b", "table": "customers"},
        {"source_id": "pgsrc", "alias": "c", "table": "products"},
    ]
    body["steps"] = [
        {"op": "join", "left": "a", "right": "b", "on": "id", "how": "inner", "output_id": "ab"},
        {"op": "join", "left": "ab", "right": "c", "on": "id", "how": "inner", "output_id": "abc"},
    ]
    r = c.post("/api/pipelines", json=body)
    assert r.status_code == 200, r.text
