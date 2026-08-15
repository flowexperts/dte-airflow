"""A sweep must be validated like a trigger (plan 053).

`POST /pipelines/{id}/trigger` refuses an eval run whose pipeline reads a
different corpus than the labels describe — the run would otherwise
complete green having matched no labels and scored a flat zero.

`start_eval_run`, which the sweep launcher calls, skipped that check. It
was tolerable while the sweep was a side door reached from an eval set that
already knew its own corpus. Plan 053 makes the sweep the *primary* path
into scoring, and there the mismatch is worse than one bad run: every cell
of the matrix inherits it, so the whole comparison reports zero — and pays
for the privilege on every model cell.

One rule, one implementation, both callers.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.eval import EvalSetBase
from dte.models.pipeline import Pipeline, SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _steps():
    return [
        {"op": "extract", "source_field": "path", "provider": "pdfplumber",
         "granularity": "page", "output_field": "content", "params": {}},
        {"op": "structure", "input_field": "content", "provider": "regex",
         "on_error": "null", "params": {},
         "model": {"instructions": "", "fields": [
             {"name": "total", "type": "string", "pattern": r"(\d+)"}]}},
    ]


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    for sid in ("docs_a", "docs_b"):
        _run(fake_stores["source"].save(SourceCreate(
            id=sid, connection_id="local_fs", source_type="documents",
            config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table=sid,
        )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="set_a", name="Corpus A", source_id="docs_a",
        field_specs=[{"name": "total", "type": "numeric"}],
    )))
    # Reads docs_b — a different corpus from the one set_a labels.
    _run(fake_stores["pipeline"].save(Pipeline(
        id="mismatched", name="Mismatched", sources=["docs_b"], steps=_steps(),
        output_id=None, pipeline_type="eval",
    )))
    _run(fake_stores["pipeline"].save(Pipeline(
        id="matched", name="Matched", sources=["docs_a"], steps=_steps(),
        output_id=None, pipeline_type="eval",
    )))
    return c


class TestSweepRefusesAMismatchedCorpus:
    def test_sweep_refuses_the_mismatch_the_trigger_already_refused(self, client):
        r = client.post(
            "/api/eval-sets/set_a/sweep",
            json={"pipeline_id": "mismatched", "matrix": {"provider": ["regex"]},
                  "confirm": True},
        )
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "docs_a" in detail and "docs_b" in detail

    def test_the_estimate_refuses_it_too(self, client):
        # Refusing only at confirm would let someone build a matrix, read a
        # cost estimate, and discover the mismatch after deciding to spend.
        r = client.post(
            "/api/eval-sets/set_a/sweep",
            json={"pipeline_id": "mismatched", "matrix": {"provider": ["regex"]}},
        )
        assert r.status_code == 422

    def test_no_runs_are_enqueued_when_refused(self, client, fake_stores):
        client.post(
            "/api/eval-sets/set_a/sweep",
            json={"pipeline_id": "mismatched", "matrix": {"provider": ["regex"]},
                  "confirm": True},
        )
        assert _run(fake_stores["run"].list_for_eval_set("set_a")) == []

    def test_the_matching_pipeline_still_estimates(self, client):
        r = client.post(
            "/api/eval-sets/set_a/sweep",
            json={"pipeline_id": "matched", "matrix": {"provider": ["regex"]}},
        )
        assert r.status_code == 200
        assert r.json()["cells"] == 1
        assert r.json()["enqueued"] is False

    def test_trigger_still_refuses_it(self, client):
        # The behaviour being shared must not be lost from where it started.
        r = client.post(
            "/api/pipelines/mismatched/trigger", json={"eval_set_id": "set_a"}
        )
        assert r.status_code == 422
