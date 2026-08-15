"""`POST /api/eval-sets/{id}/propose` — LLM-as-judge labels (plan 051 task 14).

The fastest cold start and the most dangerous one. A single model proposing
ground truth means part of the corpus is that model's opinion, so every
score computed against it is partly the model grading itself. Nothing here
prevents that — it is a legitimate way to start — but two things make it
impossible to forget:

* the labels are permanently tagged `judge`, never folded into `human`;
* writing requires explicit confirmation, so proposals can be read first.

The >50%-judge warning on the leaderboard is what closes the loop, and it
only works because the tag survives.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.eval import EvalSetBase
from dte.models.pipeline import SourceCreate

DOC_A = "a" * 64
DOC_B = "b" * 64


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="jp_src", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="jp_set", name="Invoices", source_id="jp_src",
        field_specs=[{"name": "invoice_no", "type": "string"}],
    )))
    assert c.post("/api/pipelines", json={
        "id": "jp_v1", "name": "jp_v1", "sources": ["jp_src"], "output_id": None,
        "pipeline_type": "eval",
        "steps": [
            {"op": "extract", "source_field": "path", "provider": "pdfplumber",
             "granularity": "page", "output_field": "content", "params": {}},
            {"op": "structure", "input_field": "content", "provider": "claude",
             "on_error": "null", "params": {},
             "model": {"instructions": "", "fields": [
                 {"name": "invoice_no", "type": "string", "required": False,
                  "description": "n"}]}},
        ],
    }).status_code == 200
    yield c, fake_stores


def _patch_rows(monkeypatch, rows):
    from dte.api.routes import evals as ev

    async def fake(pipeline, *a, **kw):
        return rows

    monkeypatch.setattr(ev, "materialise_pipeline_rows", fake)


def test_propose_without_confirm_writes_nothing(client, monkeypatch):
    c, stores = client
    _patch_rows(monkeypatch, [
        {"artifact_ref": f"artifact://{DOC_A}", "invoice_no": "INV-1"},
    ])
    r = c.post("/api/eval-sets/jp_set/propose", json={"pipeline_id": "jp_v1"})
    assert r.status_code == 200, r.text
    assert r.json()["written"] == 0
    assert len(r.json()["proposals"]) == 1
    assert _run(stores["eval_example"].list_for_set("jp_set", limit=99)) == []


def test_confirmed_proposals_are_tagged_judge_forever(client, monkeypatch):
    c, stores = client
    _patch_rows(monkeypatch, [
        {"artifact_ref": f"artifact://{DOC_A}", "invoice_no": "INV-1"},
        {"artifact_ref": f"artifact://{DOC_B}", "invoice_no": "INV-2"},
    ])
    r = c.post("/api/eval-sets/jp_set/propose",
               json={"pipeline_id": "jp_v1", "confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["written"] == 2

    examples = _run(stores["eval_example"].list_for_set("jp_set", limit=99))
    assert {e.label_source for e in examples} == {"judge"}
    assert _run(stores["eval_set"].get("jp_set")).labels_version == 2


def test_documents_the_judge_abstained_on_are_not_labeled(client, monkeypatch):
    """A null proposal is not a label. Writing it would assert that the
    correct answer is 'nothing', and any extractor that also abstains would
    then score a perfect hit on it."""
    c, stores = client
    _patch_rows(monkeypatch, [
        {"artifact_ref": f"artifact://{DOC_A}", "invoice_no": None},
        {"artifact_ref": f"artifact://{DOC_B}", "invoice_no": "INV-2"},
    ])
    r = c.post("/api/eval-sets/jp_set/propose",
               json={"pipeline_id": "jp_v1", "confirm": True})
    assert r.json()["written"] == 1
    examples = _run(stores["eval_example"].list_for_set("jp_set", limit=99))
    assert [e.doc_key for e in examples] == [DOC_B]


def test_unknown_pipeline_422s(client, monkeypatch):
    c, _ = client
    _patch_rows(monkeypatch, [])
    r = c.post("/api/eval-sets/jp_set/propose", json={"pipeline_id": "ghost"})
    assert r.status_code == 422, r.text
