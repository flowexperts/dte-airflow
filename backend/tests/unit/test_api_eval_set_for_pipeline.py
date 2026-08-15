"""An eval set derived from the pipeline, not typed a second time (plan 053).

The builder used to carry this warning above the field rows: "These names
must match what your pipeline's `structure` step produces — scoring joins
them by name. A name that doesn't match won't error; it scores zero on
every document, which reads as a broken extractor."

A warning that a hand-copied list must stay in sync is a design admitting
it asked for the wrong thing. The pipeline already declares the fields.
This endpoint derives the set from it, so the two cannot disagree.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import Pipeline, SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _steps(fields=None):
    return [
        {"op": "extract", "source_field": "path", "provider": "pdfplumber",
         "granularity": "page", "output_field": "content", "params": {}},
        {"op": "structure", "input_field": "content", "provider": "claude",
         "on_error": "null", "params": {},
         "model": {"instructions": "", "fields": fields or [
             {"name": "total", "type": "float", "description": "grand total"},
             {"name": "vendor", "type": "string", "description": "who billed"}]}},
    ]


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="docs", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["pipeline"].save(Pipeline(
        id="invoices", name="Invoices", sources=["docs"], steps=_steps(),
        output_id=None, pipeline_type="eval",
    )))
    return c


class TestDerivation:
    def test_creates_a_set_from_the_pipeline(self, client):
        r = client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"})
        assert r.status_code == 201, r.text
        assert r.json()["created"] is True

    def test_field_specs_match_the_structure_step(self, client, fake_stores):
        body = client.post(
            "/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"}
        ).json()
        s = _run(fake_stores["eval_set"].get(body["eval_set_id"]))
        assert [f["name"] for f in s.field_specs] == ["total", "vendor"]
        assert [f["type"] for f in s.field_specs] == ["numeric", "string"]

    def test_binds_to_the_pipelines_documents_source(self, client, fake_stores):
        body = client.post(
            "/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"}
        ).json()
        s = _run(fake_stores["eval_set"].get(body["eval_set_id"]))
        assert s.source_id == "docs"

    def test_picks_the_documents_source_among_several(self, client, fake_stores):
        # A pipeline may join a lookup table alongside the corpus. Only the
        # documents source can be scored against.
        _run(fake_stores["source"].save(SourceCreate(
            id="rates", connection_id="local_fs", source_type="filesystem",
            config={"bucket_url": "/tmp", "file_glob": "*.json"}, table="rates",
        )))
        _run(fake_stores["pipeline"].save(Pipeline(
            id="joined", name="Joined", sources=["rates", "docs"], steps=_steps(),
            output_id=None, pipeline_type="eval",
        )))
        body = client.post(
            "/api/eval-sets:for-pipeline", json={"pipeline_id": "joined"}
        ).json()
        s = _run(fake_stores["eval_set"].get(body["eval_set_id"]))
        assert s.source_id == "docs"

    def test_names_the_set_after_the_pipeline(self, client, fake_stores):
        body = client.post(
            "/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"}
        ).json()
        s = _run(fake_stores["eval_set"].get(body["eval_set_id"]))
        assert "Invoices" in s.name


class TestIdempotence:
    def test_second_call_returns_the_same_set(self, client):
        first = client.post(
            "/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"}
        ).json()
        second = client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"})
        assert second.status_code == 200
        assert second.json()["eval_set_id"] == first["eval_set_id"]
        assert second.json()["created"] is False

    def test_second_call_creates_no_second_set(self, client, fake_stores):
        client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"})
        client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"})
        assert len(_run(fake_stores["eval_set"].list())) == 1

    def test_two_pipelines_on_the_same_fields_share_one_set(self, client, fake_stores):
        # This is the point. Comparing claude against openai means two eval
        # pipelines over one corpus; if each minted its own set, their
        # scores would live on separate leaderboards and never rank.
        _run(fake_stores["pipeline"].save(Pipeline(
            id="invoices_oai", name="Invoices OAI", sources=["docs"], steps=_steps(),
            output_id=None, pipeline_type="eval",
        )))
        a = client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"})
        b = client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices_oai"})
        assert a.json()["eval_set_id"] == b.json()["eval_set_id"]

    def test_reordering_fields_reuses_the_set(self, client, fake_stores):
        # A cosmetic edit in the builder must not orphan the labels.
        client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"})
        _run(fake_stores["pipeline"].save(Pipeline(
            id="reordered", name="Reordered", sources=["docs"],
            steps=_steps([
                {"name": "vendor", "type": "string", "description": "who billed"},
                {"name": "total", "type": "float", "description": "grand total"},
            ]),
            output_id=None, pipeline_type="eval",
        )))
        r = client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "reordered"})
        assert r.json()["created"] is False

    def test_adding_a_field_mints_a_new_set(self, client, fake_stores):
        # Genuinely a different task now — prior scores are not comparable.
        first = client.post(
            "/api/eval-sets:for-pipeline", json={"pipeline_id": "invoices"}
        ).json()
        _run(fake_stores["pipeline"].save(Pipeline(
            id="more", name="More", sources=["docs"],
            steps=_steps([
                {"name": "total", "type": "float"},
                {"name": "vendor", "type": "string"},
                {"name": "due_date", "type": "date"},
            ]),
            output_id=None, pipeline_type="eval",
        )))
        second = client.post(
            "/api/eval-sets:for-pipeline", json={"pipeline_id": "more"}
        ).json()
        assert second["eval_set_id"] != first["eval_set_id"]
        assert second["created"] is True


class TestRejections:
    def test_unknown_pipeline_404s(self, client):
        r = client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "nope"})
        assert r.status_code == 404

    def test_no_structure_step_is_refused(self, client, fake_stores):
        _run(fake_stores["pipeline"].save(Pipeline(
            id="plain", name="Plain", sources=["docs"],
            steps=[{"op": "select", "fields": [{"field": "path"}]}],
            output_id=None, pipeline_type="transform",
        )))
        r = client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "plain"})
        assert r.status_code == 422
        assert "structure" in r.json()["detail"]

    def test_no_documents_source_is_refused(self, client, fake_stores):
        _run(fake_stores["source"].save(SourceCreate(
            id="rows", connection_id="local_fs", source_type="filesystem",
            config={"bucket_url": "/tmp", "file_glob": "*.json"}, table="rows",
        )))
        _run(fake_stores["pipeline"].save(Pipeline(
            id="tabular", name="Tabular", sources=["rows"], steps=_steps(),
            output_id=None, pipeline_type="transform",
        )))
        r = client.post("/api/eval-sets:for-pipeline", json={"pipeline_id": "tabular"})
        assert r.status_code == 422
        assert "documents" in r.json()["detail"]
