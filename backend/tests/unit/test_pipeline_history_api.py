"""API-level tests for the pipeline revision GET routes (plan 037 branch 2)."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import DestinationCreate, SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _pipeline(name: str = "orig", steps=None):
    return {
        "id": "p_hist",
        "name": name,
        "sources": ["src_hist"],
        "steps": steps if steps is not None else [],
        "output_id": "dst_hist",
    }


@pytest.fixture
def client(fake_stores):
    s = fake_stores["source"]
    d = fake_stores["destination"]
    _run(s.save(SourceCreate(
        id="src_hist", connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": "/tmp"}, table="dummy",
    )))
    _run(d.save(DestinationCreate(
        id="dst_hist", connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/hist.json"},
    )))
    yield TestClient(app), fake_stores


def test_list_revisions_returns_newest_first(client):
    c, _ = client
    c.post("/api/pipelines", json=_pipeline(name="v0"))
    c.put("/api/pipelines/p_hist", json=_pipeline(name="v1"))
    c.put("/api/pipelines/p_hist", json=_pipeline(name="v2"))
    r = c.get("/api/pipelines/p_hist/revisions")
    assert r.status_code == 200, r.text
    revs = r.json()
    names = [rev["config"]["name"] for rev in revs]
    assert names == ["v2", "v1", "v0"]


def test_list_revisions_missing_pipeline_returns_404(client):
    c, _ = client
    assert c.get("/api/pipelines/does-not-exist/revisions").status_code == 404


def test_get_revision_returns_config(client):
    c, stores = client
    c.post("/api/pipelines", json=_pipeline())
    rev_id = _run(stores["pipeline_revision"].latest_for_pipeline("p_hist")).id
    r = c.get(f"/api/pipelines/p_hist/revisions/{rev_id}")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == rev_id
    assert r.json()["config"]["name"] == "orig"


def test_get_revision_wrong_pipeline_returns_404(client):
    c, stores = client
    c.post("/api/pipelines", json=_pipeline())
    rev_id = _run(stores["pipeline_revision"].latest_for_pipeline("p_hist")).id
    # ask for it under a different pipeline path
    assert c.get(f"/api/pipelines/other/revisions/{rev_id}").status_code == 404


def test_diff_endpoint_returns_structured_diff(client):
    c, stores = client
    c.post("/api/pipelines", json=_pipeline(name="v0"))
    c.put("/api/pipelines/p_hist", json=_pipeline(
        name="v1", steps=[{"op": "sort", "by": ["x"]}],
    ))
    revs = _run(stores["pipeline_revision"].list_for_pipeline("p_hist"))
    assert len(revs) == 2
    older, newer = revs[1].id, revs[0].id  # list is newest-first
    r = c.get(f"/api/pipelines/p_hist/diff?from={older}&to={newer}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["diff"]["name_changed"] is True
    assert body["diff"]["name_after"] == "v1"
    assert len(body["diff"]["steps"]) == 1
    assert body["diff"]["steps"][0]["kind"] == "added"
    assert body["diff"]["steps"][0]["op"] == "sort"
    assert "sort" in body["summary"]


def test_diff_missing_revision_returns_404(client):
    c, stores = client
    c.post("/api/pipelines", json=_pipeline())
    rev_id = _run(stores["pipeline_revision"].latest_for_pipeline("p_hist")).id
    r = c.get(f"/api/pipelines/p_hist/diff?from={rev_id}&to=missing-rev")
    assert r.status_code == 404


def test_put_populates_summary_from_prior_revision(client):
    c, stores = client
    c.post("/api/pipelines", json=_pipeline(name="v0"))
    c.put("/api/pipelines/p_hist", json=_pipeline(name="v1"))
    revs = _run(stores["pipeline_revision"].list_for_pipeline("p_hist"))
    # v1 was created against the v0 prior — summary should mention the name change.
    latest = revs[0]
    assert latest.summary is not None
    assert "v0" in latest.summary and "v1" in latest.summary
    # First revision has no prior, so its summary stays None.
    first = revs[1]
    assert first.summary is None


def test_get_revision_returns_yaml_of_config(client):
    import yaml
    c, stores = client
    c.post("/api/pipelines", json=_pipeline())
    rev_id = _run(stores["pipeline_revision"].latest_for_pipeline("p_hist")).id
    body = c.get(f"/api/pipelines/p_hist/revisions/{rev_id}").json()
    assert yaml.safe_load(body["yaml"]) == body["config"]


def test_diff_endpoint_pairs_yaml_lines_side_by_side(client):
    c, stores = client
    c.post("/api/pipelines", json=_pipeline(name="v0"))
    c.put("/api/pipelines/p_hist", json=_pipeline(name="v1", steps=[{"op": "sort", "by": ["x"]}]))
    revs = _run(stores["pipeline_revision"].list_for_pipeline("p_hist"))
    body = c.get(f"/api/pipelines/p_hist/diff?from={revs[1].id}&to={revs[0].id}").json()
    rows = [r for hunk in body["yaml_diff"] for r in hunk]
    renamed = next(r for r in rows if r["kind"] == "replace" and r["a"] == "name: v0")
    assert renamed["b"] == "name: v1" and renamed["a_no"] == renamed["b_no"]
    # an added line has nothing on the left
    assert any(r["a"] is None and r["b"] and "sort" in r["b"] for r in rows)
    assert all(r["kind"] == "equal" or r["a"] != r["b"] for r in rows)
    same = c.get(f"/api/pipelines/p_hist/diff?from={revs[0].id}&to={revs[0].id}").json()
    assert same["yaml_diff"] == []
