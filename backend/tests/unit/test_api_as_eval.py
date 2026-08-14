"""Turning a transform pipeline into its eval twin (plan 053).

Before this endpoint, `pipeline_type` could only be set on create — the
builder's Segmented control is mounted by `/pipelines/new` and nowhere
else. So a user with a working extraction pipeline could not evaluate it
without rebuilding the whole thing by hand in a second pipeline, retyping
every field, and hoping the two stayed identical. The comparison would then
be measuring their typing.

Two properties carry the endpoint:

**Idempotence.** Compare is a button someone will press twice. The second
press must land on the same twin, not accumulate `__eval`, `__eval__eval`,
each with its own runs and its own share of the leaderboard.

**Sweepable-key normalisation.** `apply_cell` refuses to create a leaf that
does not already exist, so a `params.model` sweep 422s against a step that
never named a model. The guard is right — it is what stops a typo'd axis
becoming N identical cells — so the twin is filled in instead.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import DestinationCreate, Pipeline, SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _steps(provider="claude", params=None):
    return [
        {"op": "extract", "source_field": "path", "provider": "pdfplumber",
         "granularity": "page", "output_field": "content", "params": {}},
        {"op": "structure", "input_field": "content", "provider": provider,
         "on_error": "null", "params": params if params is not None else {},
         "model": {"instructions": "read the invoice", "fields": [
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
    _run(fake_stores["destination"].save(DestinationCreate(
        id="out", connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/out.json"},
    )))
    _run(fake_stores["pipeline"].save(Pipeline(
        id="invoices", name="Invoices", sources=["docs"], steps=_steps(),
        output_id="out", pipeline_type="transform",
    )))
    return c


class TestTwinShape:
    def test_creates_an_eval_twin(self, client):
        r = client.post("/api/pipelines/invoices/as-eval")
        assert r.status_code == 201, r.text
        assert r.json()["pipeline_id"] == "invoices__eval"

    def test_twin_is_an_eval_pipeline_with_no_destination(self, client, fake_stores):
        client.post("/api/pipelines/invoices/as-eval")
        twin = _run(fake_stores["pipeline"].get("invoices__eval"))
        assert twin.pipeline_type == "eval"
        assert not twin.output_id

    def test_twin_reads_the_same_sources(self, client, fake_stores):
        # The corpus-match rule refuses an eval run whose pipeline reads
        # different documents. A twin that dropped the source would be
        # rejected by the very next call in the flow.
        client.post("/api/pipelines/invoices/as-eval")
        twin = _run(fake_stores["pipeline"].get("invoices__eval"))
        assert twin.sources == ["docs"]

    def test_steps_are_copied_verbatim(self, client, fake_stores):
        # Minus the params normalisation below, which only fills a key that
        # was absent. The extraction being scored must be the extraction
        # that ships, or the score is about a different pipeline.
        client.post("/api/pipelines/invoices/as-eval")
        base = _run(fake_stores["pipeline"].get("invoices"))
        twin = _run(fake_stores["pipeline"].get("invoices__eval"))
        assert twin.steps[0] == base.steps[0]
        b, t = base.steps[1], twin.steps[1]
        assert t["model"] == b["model"] and t["provider"] == b["provider"]

    def test_base_pipeline_is_untouched(self, client, fake_stores):
        client.post("/api/pipelines/invoices/as-eval")
        base = _run(fake_stores["pipeline"].get("invoices"))
        assert base.pipeline_type == "transform"
        assert base.output_id == "out"


class TestIdempotence:
    def test_second_call_returns_the_same_twin(self, client):
        first = client.post("/api/pipelines/invoices/as-eval").json()
        second = client.post("/api/pipelines/invoices/as-eval")
        assert second.status_code == 200
        assert second.json()["pipeline_id"] == first["pipeline_id"]

    def test_second_call_creates_no_second_pipeline(self, client, fake_stores):
        client.post("/api/pipelines/invoices/as-eval")
        client.post("/api/pipelines/invoices/as-eval")
        rows = _run(fake_stores["pipeline"].list())
        assert sum(1 for p in rows if p.pipeline_type == "eval") == 1

    def test_second_call_reports_it_reused(self, client):
        assert client.post("/api/pipelines/invoices/as-eval").json()["created"] is True
        assert client.post("/api/pipelines/invoices/as-eval").json()["created"] is False

    def test_an_eval_pipeline_is_its_own_twin(self, client, fake_stores):
        # Pressing Compare on a pipeline that is already an eval pipeline
        # must not mint `invoices__eval__eval`.
        _run(fake_stores["pipeline"].save(Pipeline(
            id="already", name="Already", sources=["docs"], steps=_steps(),
            output_id=None, pipeline_type="eval",
        )))
        r = client.post("/api/pipelines/already/as-eval")
        assert r.status_code == 200
        assert r.json() == {"pipeline_id": "already", "created": False}


class TestSweepableKeys:
    def test_model_param_is_filled_from_the_provider_default(self, client, fake_stores):
        client.post("/api/pipelines/invoices/as-eval")
        twin = _run(fake_stores["pipeline"].get("invoices__eval"))
        assert twin.steps[1]["params"]["model"] == "claude-opus-5"

    def test_openai_gets_its_own_default(self, client, fake_stores):
        _run(fake_stores["pipeline"].save(Pipeline(
            id="oai", name="OAI", sources=["docs"], steps=_steps(provider="openai"),
            output_id="out", pipeline_type="transform",
        )))
        client.post("/api/pipelines/oai/as-eval")
        twin = _run(fake_stores["pipeline"].get("oai__eval"))
        assert twin.steps[1]["params"]["model"] == "gpt-5"

    def test_an_explicit_model_is_not_overwritten(self, client, fake_stores):
        _run(fake_stores["pipeline"].save(Pipeline(
            id="pinned", name="Pinned", sources=["docs"],
            steps=_steps(params={"model": "claude-haiku-4-5"}),
            output_id="out", pipeline_type="transform",
        )))
        client.post("/api/pipelines/pinned/as-eval")
        twin = _run(fake_stores["pipeline"].get("pinned__eval"))
        assert twin.steps[1]["params"]["model"] == "claude-haiku-4-5"

    def test_regex_gets_no_model_param(self, client, fake_stores):
        # regex makes no model calls. A `model` key on it would appear in
        # the sweep UI as an axis that changes nothing.
        _run(fake_stores["pipeline"].save(Pipeline(
            id="rx", name="RX", sources=["docs"], steps=_steps(provider="regex"),
            output_id="out", pipeline_type="transform",
        )))
        client.post("/api/pipelines/rx/as-eval")
        twin = _run(fake_stores["pipeline"].get("rx__eval"))
        assert "model" not in twin.steps[1]["params"]

    def test_instructions_key_exists_so_it_can_be_swept(self, client, fake_stores):
        # `apply_cell` refuses `model.instructions` when the key is absent.
        _run(fake_stores["pipeline"].save(Pipeline(
            id="noinstr", name="No instructions", sources=["docs"],
            steps=[
                _steps()[0],
                {"op": "structure", "input_field": "content", "provider": "claude",
                 "on_error": "null", "params": {},
                 "model": {"fields": [{"name": "total", "type": "float"}]}},
            ],
            output_id="out", pipeline_type="transform",
        )))
        client.post("/api/pipelines/noinstr/as-eval")
        twin = _run(fake_stores["pipeline"].get("noinstr__eval"))
        assert "instructions" in twin.steps[1]["model"]

    def test_normalised_twin_survives_a_params_model_sweep(self, client, fake_stores):
        # The end the normalisation exists for: sweeping `params.model`
        # against an un-normalised step raises "no 'model' under 'params'".
        from dte.evals.sweep import apply_cell

        client.post("/api/pipelines/invoices/as-eval")
        twin = _run(fake_stores["pipeline"].get("invoices__eval"))
        variant = apply_cell(twin, {"params.model": "claude-haiku-4-5"})
        assert variant.steps[1]["params"]["model"] == "claude-haiku-4-5"


class TestRejections:
    def test_unknown_pipeline_404s(self, client):
        assert client.post("/api/pipelines/nope/as-eval").status_code == 404

    def test_a_pipeline_with_no_structure_step_is_refused(self, client, fake_stores):
        # There is nothing to compare configs *of*. Saying so beats creating
        # a twin whose every sweep 422s later for a reason further away.
        _run(fake_stores["pipeline"].save(Pipeline(
            id="plain", name="Plain", sources=["docs"],
            steps=[{"op": "select", "fields": [{"field": "path"}]}],
            output_id="out", pipeline_type="transform",
        )))
        r = client.post("/api/pipelines/plain/as-eval")
        assert r.status_code == 422
        assert "structure" in r.json()["detail"]

    def test_a_pipeline_with_no_documents_source_is_refused(self, client, fake_stores):
        # Labels key by document hash; only a documents source produces one.
        _run(fake_stores["source"].save(SourceCreate(
            id="rows", connection_id="local_fs", source_type="filesystem",
            config={"bucket_url": "/tmp", "file_glob": "*.json"}, table="rows",
        )))
        _run(fake_stores["pipeline"].save(Pipeline(
            id="tabular", name="Tabular", sources=["rows"], steps=_steps(),
            output_id="out", pipeline_type="transform",
        )))
        r = client.post("/api/pipelines/tabular/as-eval")
        assert r.status_code == 422
        assert "documents" in r.json()["detail"]
