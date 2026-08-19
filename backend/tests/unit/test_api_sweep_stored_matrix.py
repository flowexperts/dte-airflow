"""A sweep with no matrix in the body runs the pipeline's own (plan 055).

The matrix is now a property of the eval pipeline. A caller that already
knows which pipeline to sweep should not have to restate what that pipeline
already says it varies — and some callers have no body to put it in at all.
The scheduler is the one that matters: a scheduled eval run is a comparison
run, and before this it could only ever have been N=1.

The body stays authoritative when supplied, because the estimate/confirm
pair must price exactly what the user is looking at, including edits they
have not saved.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.eval import EvalSetBase
from dte.models.pipeline import SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _structure(provider="regex"):
    return {
        "op": "structure", "input_field": "content", "provider": provider,
        "on_error": "null", "params": {"model": "claude-opus-5"},
        "model": {"instructions": "", "fields": [
            {"name": "total", "type": "string", "required": False,
             "pattern": r"Total: \$([\d,.]+)", "description": "d"}]},
    }


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="sm_src", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="sm_set", name="Invoices", source_id="sm_src",
        field_specs=[{"name": "total", "type": "numeric"}],
    )))
    assert c.post("/api/pipelines", json={
        "id": "sm_base", "name": "sm base", "sources": ["sm_src"],
        "output_id": None, "pipeline_type": "eval",
        "matrix": {"provider": ["regex", "claude"]},
        "steps": [
            {"op": "extract", "source_field": "path", "provider": "pdfplumber",
             "granularity": "page", "output_field": "content", "params": {}},
            _structure(),
        ],
    }).status_code == 200
    yield c, fake_stores


def _sweep(c, **body):
    return c.post("/api/eval-sets/sm_set/sweep", json={"pipeline_id": "sm_base", **body})


def test_omitted_matrix_falls_back_to_the_stored_one(client):
    c, _ = client
    body = _sweep(c).json()
    # Two providers stored → two cells, without the caller saying so.
    assert body["cells"] == 2


def test_body_matrix_still_wins(client):
    """Estimate and confirm must price what is on screen, including edits
    the user has not saved yet."""
    c, _ = client
    body = _sweep(c, matrix={"provider": ["regex"]}).json()
    assert body["cells"] == 1


def test_pipeline_with_no_stored_matrix_is_a_single_cell(client):
    """N=1 stays first-class — this is the nightly regression run."""
    c, _ = client
    assert c.post("/api/pipelines", json={
        "id": "sm_plain", "name": "sm plain", "sources": ["sm_src"],
        "output_id": None, "pipeline_type": "eval",
        "steps": [
            {"op": "extract", "source_field": "path", "provider": "pdfplumber",
             "granularity": "page", "output_field": "content", "params": {}},
            _structure(),
        ],
    }).status_code == 200
    body = c.post("/api/eval-sets/sm_set/sweep",
                  json={"pipeline_id": "sm_plain"}).json()
    assert body["cells"] == 1


def test_estimate_still_enqueues_nothing(client):
    c, stores = client
    _sweep(c)
    assert _run(stores["run"].list_for_pipeline("sm_base", 50)) == []
