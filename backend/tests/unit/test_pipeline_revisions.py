"""Unit tests for the PipelineRevision store + write-on-save flow.

Branch 1 scope (plan 037):
- Every accepted POST/PUT on /api/pipelines* records one revision row.
- Triggering a pipeline creates a Run whose `revision_id` matches the
  latest revision id at the moment of trigger.
- The FakePipelineRevisionStore behaves as an append-only history.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import (
    DestinationCreate,
    PipelineRevisionBase,
    SourceCreate,
)
from tests.fakes import FakePipelineRevisionStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _pipeline(pipeline_id: str = "p_rev", name: str = "orig"):
    return {
        "id": pipeline_id,
        "name": name,
        "sources": ["src_rev"],
        "steps": [],
        "output_id": "dst_rev",
    }


@pytest.fixture
def client(fake_stores):
    """Seed the default local source + destination so pipeline POST/PUT
    passes ref validation. Uses the autouse `fake_stores` fixture so all
    stores — including the revision store — are already wired."""
    s_store = fake_stores["source"]
    d_store = fake_stores["destination"]
    _run(s_store.save(SourceCreate(
        id="src_rev", connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": "/tmp"}, table="dummy",
    )))
    _run(d_store.save(DestinationCreate(
        id="dst_rev", connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/rev.json"},
    )))
    yield TestClient(app), fake_stores


def test_post_pipeline_writes_one_revision(client):
    c, stores = client
    r = c.post("/api/pipelines", json=_pipeline())
    assert r.status_code == 200, r.text
    revs = _run(stores["pipeline_revision"].list_for_pipeline("p_rev"))
    assert len(revs) == 1
    assert revs[0].pipeline_id == "p_rev"
    assert revs[0].config["name"] == "orig"
    # Fake_test_user id = "test-user"
    assert revs[0].changed_by == "test-user"


def test_put_pipeline_appends_a_revision(client):
    c, stores = client
    c.post("/api/pipelines", json=_pipeline())
    r = c.put("/api/pipelines/p_rev", json=_pipeline(name="renamed"))
    assert r.status_code == 200, r.text
    revs = _run(stores["pipeline_revision"].list_for_pipeline("p_rev"))
    assert len(revs) == 2
    # list_for_pipeline returns newest first
    assert revs[0].config["name"] == "renamed"
    assert revs[1].config["name"] == "orig"


def test_multiple_puts_produce_ordered_history(client):
    c, stores = client
    c.post("/api/pipelines", json=_pipeline(name="v0"))
    for name in ("v1", "v2", "v3"):
        assert c.put("/api/pipelines/p_rev", json=_pipeline(name=name)).status_code == 200
    revs = _run(stores["pipeline_revision"].list_for_pipeline("p_rev"))
    names = [r.config["name"] for r in revs]
    assert names == ["v3", "v2", "v1", "v0"]


def test_trigger_pins_run_to_latest_revision(client):
    c, stores = client
    c.post("/api/pipelines", json=_pipeline(name="v0"))
    c.put("/api/pipelines/p_rev", json=_pipeline(name="v1"))
    latest = _run(stores["pipeline_revision"].latest_for_pipeline("p_rev"))
    assert latest is not None
    r = c.post("/api/pipelines/p_rev/trigger")
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    run = _run(stores["run"].get(run_id))
    assert run["revision_id"] == latest.id


def test_revision_store_get_and_latest():
    store = FakePipelineRevisionStore()
    _run(store.save(PipelineRevisionBase(
        id="r1", pipeline_id="p1", config={"name": "a"}, changed_by="u1",
    )))
    _run(store.save(PipelineRevisionBase(
        id="r2", pipeline_id="p1", config={"name": "b"}, changed_by="u1",
    )))
    _run(store.save(PipelineRevisionBase(
        id="r3", pipeline_id="p2", config={"name": "other"}, changed_by="u1",
    )))
    assert _run(store.get("r1")).config["name"] == "a"
    assert _run(store.get("missing")) is None
    p1_revs = _run(store.list_for_pipeline("p1"))
    assert {r.id for r in p1_revs} == {"r1", "r2"}
    latest = _run(store.latest_for_pipeline("p1"))
    assert latest is not None and latest.id == "r2"
    assert _run(store.latest_for_pipeline("nonexistent")) is None
