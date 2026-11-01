"""`check` and `profile` belong to quality pipelines only (plan 086 task 0).

A transform run compiles without `on_quality_result`, so a check step in it
evaluates and its result goes nowhere: the run reports `completed` whatever
the check found. The builder already hides quality ops outside quality
pipelines; the API now refuses them too. Reads stay lenient, so a revision
saved before this rule still loads and runs.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import (
    DestinationCreate,
    Pipeline,
    PipelineRevisionBase,
    SourceCreate,
)

CHECK = {"op": "check", "expr": "age > 18"}
PROFILE = {"op": "profile"}
STRUCTURE = {
    "op": "structure", "input_field": "name", "provider": "regex",
    "on_error": "null", "params": {},
    "model": {"instructions": "x", "fields": [
        {"name": "n", "type": "string", "required": False, "description": "d", "pattern": "a"}]},
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores, sample_json_file, tmp_path):
    _run(fake_stores["source"].save(SourceCreate(
        id="people", connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": sample_json_file, "file_glob": ""}, table="people",
    )))
    _run(fake_stores["destination"].save(DestinationCreate(
        id="out", connection_id="local_fs",
        config={"type": "json_file", "path": str(tmp_path / "out.json")},
    )))
    return TestClient(app)


def _body(ptype, steps):
    return {
        "id": "p", "name": "p", "sources": ["people"], "steps": steps,
        "pipeline_type": ptype, "output_id": "out" if ptype == "transform" else None,
    }


@pytest.mark.parametrize("ptype,steps,op", [
    ("transform", [CHECK], "check"),
    ("transform", [PROFILE], "profile"),
    ("eval", [STRUCTURE, CHECK], "check"),
])
def test_post_rejects_quality_op_outside_quality(client, ptype, steps, op):
    r = client.post("/api/pipelines", json=_body(ptype, steps))
    assert r.status_code == 422
    assert f"Step op {op!r} is not allowed in {ptype} pipelines" in r.text


def test_put_rejects_check_on_transform(client):
    assert client.post("/api/pipelines", json=_body("transform", [])).status_code == 200
    r = client.put("/api/pipelines/p", json=_body("transform", [CHECK]))
    assert r.status_code == 422
    assert "not allowed in transform pipelines" in r.text


@pytest.mark.parametrize("steps", [[CHECK], [PROFILE]])
def test_quality_pipeline_still_accepts_them(client, steps):
    r = client.post("/api/pipelines", json=_body("quality", steps))
    assert r.status_code == 200, r.text


def test_saved_transform_with_check_still_reads_and_runs(client, fake_stores):
    """Rows written before the rule must not 500 the list or fail the run."""
    config = {**_body("transform", [CHECK]), "engine": "auto"}
    _run(fake_stores["pipeline"].save(Pipeline(**config)))
    _run(fake_stores["pipeline_revision"].save(
        PipelineRevisionBase(id="rev-old", pipeline_id="p", config=config)))

    assert client.get("/api/pipelines/p").status_code == 200
    assert client.get("/api/pipelines").status_code == 200
    r = client.post("/api/pipelines/p/trigger")
    assert r.status_code == 200, r.text
    run = _run(fake_stores["run"].get(r.json()["run_id"]))
    assert run["status"] == "completed", run
