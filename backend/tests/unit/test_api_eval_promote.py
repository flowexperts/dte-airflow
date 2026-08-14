"""Promote a winning eval config into a real transform pipeline (task 20).

This closes the loop the harness exists for. Everything upstream answers
"which extraction config should I ship"; without promote, the answer is a
number on a leaderboard that someone then re-types into the builder by
hand, which is where the config that was actually measured and the config
that actually ships quietly diverge.

The steps are copied verbatim from the winning pipeline for exactly that
reason: the promoted pipeline's extract/structure config must hash to the
same `config_digest` that earned the score, or the score is about something
else.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.evals.digest import config_digest
from dte.models.eval import EvalSetBase
from dte.models.pipeline import DestinationCreate, SourceCreate

STEPS = [
    {"op": "extract", "source_field": "path", "provider": "pdfplumber",
     "granularity": "page", "output_field": "content", "params": {}},
    {"op": "structure", "input_field": "content", "provider": "regex",
     "on_error": "null", "params": {},
     "model": {"instructions": "win", "fields": [
         {"name": "total", "type": "string", "required": False,
          "description": "d", "pattern": "x"}]}},
]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="pr_src", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["destination"].save(DestinationCreate(
        id="pr_dst", connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/pr_out.json"},
    )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="pr_set", name="Invoices", source_id="pr_src",
        field_specs=[{"name": "total", "type": "numeric"}],
    )))
    assert c.post("/api/pipelines", json={
        "id": "pr_winner", "name": "winner", "sources": ["pr_src"],
        "output_id": None, "pipeline_type": "eval", "steps": STEPS,
    }).status_code == 200
    yield c, fake_stores


def test_promote_creates_a_transform_pipeline_with_the_same_config(client):
    c, stores = client
    r = c.post("/api/eval-sets/pr_set/promote", json={
        "pipeline_id": "pr_winner", "new_pipeline_id": "invoices_prod",
        "name": "Invoices (prod)", "output_id": "pr_dst",
    })
    assert r.status_code == 201, r.text

    promoted = _run(stores["pipeline"].get("invoices_prod"))
    assert promoted is not None
    assert promoted.pipeline_type == "transform"
    assert promoted.output_id == "pr_dst"

    # The whole point: what ships must hash identically to what was scored.
    winner = _run(stores["pipeline"].get("pr_winner"))
    assert config_digest(promoted) == config_digest(winner)


def test_promote_requires_a_destination(client):
    """A transform pipeline with nowhere to write is not a shippable
    pipeline; accepting one would produce a promoted config that cannot
    run."""
    c, _ = client
    r = c.post("/api/eval-sets/pr_set/promote", json={
        "pipeline_id": "pr_winner", "new_pipeline_id": "no_dest",
        "name": "x", "output_id": "",
    })
    assert r.status_code == 422, r.text


def test_promote_refuses_to_overwrite_an_existing_pipeline(client):
    c, _ = client
    body = {
        "pipeline_id": "pr_winner", "new_pipeline_id": "invoices_prod",
        "name": "Invoices (prod)", "output_id": "pr_dst",
    }
    assert c.post("/api/eval-sets/pr_set/promote", json=body).status_code == 201
    r = c.post("/api/eval-sets/pr_set/promote", json=body)
    assert r.status_code == 409, r.text


def test_promoting_a_non_eval_pipeline_is_rejected(client):
    c, _ = client
    assert c.post("/api/pipelines", json={
        "id": "pr_tx", "name": "tx", "sources": ["pr_src"],
        "steps": [], "output_id": "pr_dst",
    }).status_code == 200
    r = c.post("/api/eval-sets/pr_set/promote", json={
        "pipeline_id": "pr_tx", "new_pipeline_id": "other",
        "name": "x", "output_id": "pr_dst",
    })
    assert r.status_code == 422, r.text
