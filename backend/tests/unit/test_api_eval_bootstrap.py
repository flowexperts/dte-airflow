"""`POST /api/eval-sets/{id}/bootstrap` (plan 051 phase 3).

The consensus arithmetic is covered by `test_eval_bootstrap.py`; this file
covers the endpoint's own contract, and the one that matters most is the
confirm gate. Bootstrap writes *ground truth*. A corpus is the thing every
future comparison is measured against, so a mis-click that silently fills
it with model output is not a small mistake — it is an eval set that looks
populated and quietly encodes whatever the models happened to agree on.

Variant execution is patched here. Running real providers would make the
test slow, paid, and non-deterministic; the compile-and-materialise path is
already covered by the scenario suite.
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


def _rows(*pairs):
    return [{"artifact_ref": f"artifact://{k}", **f} for k, f in pairs]


def _eval_pipeline(c, pid, provider="regex"):
    r = c.post("/api/pipelines", json={
        "id": pid, "name": pid, "sources": ["bs_src"], "output_id": None,
        "pipeline_type": "eval",
        "steps": [
            {"op": "extract", "source_field": "path", "provider": "pdfplumber",
             "granularity": "page", "output_field": "content", "params": {}},
            {"op": "structure", "input_field": "content", "provider": provider,
             "on_error": "null", "params": {},
             "model": {"instructions": "", "fields": [
                 {"name": "invoice_no", "type": "string", "required": False,
                  "description": "n", "pattern": r"Invoice (INV-\d+)"}]}},
        ],
    })
    assert r.status_code == 200, r.text


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="bs_src", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="bs_set", name="Invoices", source_id="bs_src",
        field_specs=[{"name": "invoice_no", "type": "string"}],
    )))
    _eval_pipeline(c, "bs_v1")
    _eval_pipeline(c, "bs_v2", provider="claude")
    yield c, fake_stores


def _patch_rows(monkeypatch, mapping):
    from dte.api.routes import evals as ev

    async def fake(pipeline, *a, **kw):
        return mapping[pipeline.id]

    monkeypatch.setattr(ev, "materialise_pipeline_rows", fake)


def test_bootstrap_without_confirm_writes_nothing(client, monkeypatch):
    """The whole point of the gate: a preview of proposed ground truth that
    costs nothing to look at and cannot corrupt the corpus."""
    c, stores = client
    _patch_rows(monkeypatch, {
        "bs_v1": _rows((DOC_A, {"invoice_no": "INV-1"})),
        "bs_v2": _rows((DOC_A, {"invoice_no": "INV-1"})),
    })

    r = c.post("/api/eval-sets/bs_set/bootstrap",
               json={"variant_pipeline_ids": ["bs_v1", "bs_v2"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] == 0
    assert len(body["agreed"]) == 1
    assert _run(stores["eval_example"].list_for_set("bs_set", limit=100)) == []
    # And the version must not move — nothing was labeled.
    assert _run(stores["eval_set"].get("bs_set")).labels_version == 1


def test_confirm_writes_agreed_labels_tagged_consensus(client, monkeypatch):
    c, stores = client
    _patch_rows(monkeypatch, {
        "bs_v1": _rows((DOC_A, {"invoice_no": "INV-1"}),
                       (DOC_B, {"invoice_no": "INV-2"})),
        "bs_v2": _rows((DOC_A, {"invoice_no": "INV-1"}),
                       (DOC_B, {"invoice_no": "DIFFERENT"})),
    })

    r = c.post("/api/eval-sets/bs_set/bootstrap",
               json={"variant_pipeline_ids": ["bs_v1", "bs_v2"], "confirm": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] == 1
    assert len(body["disagreed"]) == 1

    examples = _run(stores["eval_example"].list_for_set("bs_set", limit=100))
    assert [e.doc_key for e in examples] == [DOC_A]
    # Permanently tagged. A consensus label is not a human label, and the
    # leaderboard's judge/consensus warning depends on being able to tell.
    assert examples[0].label_source == "consensus"
    assert _run(stores["eval_set"].get("bs_set")).labels_version == 2


def test_single_variant_is_refused(client, monkeypatch):
    c, _ = client
    _patch_rows(monkeypatch, {"bs_v1": _rows((DOC_A, {"invoice_no": "INV-1"}))})
    r = c.post("/api/eval-sets/bs_set/bootstrap",
               json={"variant_pipeline_ids": ["bs_v1"], "confirm": True})
    assert r.status_code == 422, r.text


def test_shared_provider_refuses_to_auto_write(client, monkeypatch):
    """Two prompts against one model agreeing is that model's opinion twice.
    The proposals still come back for review; only the unattended write is
    refused."""
    c, stores = client
    _eval_pipeline(c, "bs_v3")  # also regex, same provider as bs_v1
    _patch_rows(monkeypatch, {
        "bs_v1": _rows((DOC_A, {"invoice_no": "INV-1"})),
        "bs_v3": _rows((DOC_A, {"invoice_no": "INV-1"})),
    })

    r = c.post("/api/eval-sets/bs_set/bootstrap",
               json={"variant_pipeline_ids": ["bs_v1", "bs_v3"], "confirm": True})
    assert r.status_code == 409, r.text
    assert "provider" in str(r.json()["detail"]).lower()
    assert _run(stores["eval_example"].list_for_set("bs_set", limit=100)) == []


def test_unknown_eval_set_404s(client, monkeypatch):
    c, _ = client
    _patch_rows(monkeypatch, {})
    r = c.post("/api/eval-sets/nope/bootstrap",
               json={"variant_pipeline_ids": ["bs_v1", "bs_v2"]})
    assert r.status_code == 404


def test_unknown_variant_pipeline_422s(client, monkeypatch):
    c, _ = client
    _patch_rows(monkeypatch, {})
    r = c.post("/api/eval-sets/bs_set/bootstrap",
               json={"variant_pipeline_ids": ["bs_v1", "ghost"]})
    assert r.status_code == 422, r.text
    assert "ghost" in str(r.json()["detail"])
