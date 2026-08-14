"""The sweep comparison route (plan 053).

`build_comparison` is unit-tested in `test_comparison.py`. This covers the
route around it: finding the sweep's cells, resolving the eval set they
were scored against, and the two ways it can be asked for something that
does not exist.
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


def _steps(provider="claude"):
    return [
        {"op": "extract", "source_field": "path", "provider": "pdfplumber",
         "granularity": "page", "output_field": "content", "params": {}},
        {"op": "structure", "input_field": "content", "provider": provider,
         "on_error": "null", "params": {"model": "claude-opus-5"},
         "model": {"instructions": "", "fields": [
             {"name": "total", "type": "float"}]}},
    ]


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="docs", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="invoices_set", name="Invoices", source_id="docs",
        field_specs=[{"name": "total", "type": "numeric"}],
    )))
    for pid, provider in (("v_claude", "claude"), ("v_openai", "openai")):
        _run(fake_stores["pipeline"].save(Pipeline(
            id=pid, name=pid, sources=["docs"], steps=_steps(provider),
            output_id=None, pipeline_type="eval",
        )))
        rid = _run(fake_stores["run"].create(pid))
        _run(fake_stores["run"].update(
            rid, status="completed", eval_set_id="invoices_set", sweep_id="sw1",
            scores={"macro_f1": 0.9 if provider == "claude" else 0.4,
                    "macro_f1_interval": [0.85, 0.95] if provider == "claude" else [0.35, 0.45],
                    "n": 40, "throughput": {"cost_usd": 0.5, "latency_p95_ms": 800}},
        ))
    return c


class TestRoute:
    def test_returns_a_cell_per_sweep_run(self, client):
        r = client.get("/api/sweeps/sw1/comparison")
        assert r.status_code == 200, r.text
        assert {c["cell_id"] for c in r.json()["cells"]} == {"v_claude", "v_openai"}

    def test_resolves_the_eval_set_from_the_runs(self, client):
        body = client.get("/api/sweeps/sw1/comparison").json()
        assert body["eval_set_id"] == "invoices_set"
        assert body["labels_version"] == 1

    def test_scores_and_ranking_come_through(self, client):
        by_id = {c["cell_id"]: c for c in client.get("/api/sweeps/sw1/comparison").json()["cells"]}
        assert by_id["v_claude"]["macro_f1"] == 0.9
        assert by_id["v_claude"]["rank"] == 1
        assert by_id["v_openai"]["rank"] == 2

    def test_cell_config_labels_the_column(self, client):
        by_id = {c["cell_id"]: c for c in client.get("/api/sweeps/sw1/comparison").json()["cells"]}
        assert by_id["v_claude"]["cell"]["provider"] == "claude"
        assert by_id["v_openai"]["cell"]["provider"] == "openai"

    def test_reports_how_many_cells_are_still_running(self, client, fake_stores):
        # The grid is polled while a sweep fills in; without this the page
        # cannot tell "openai lost" from "openai has not finished".
        _run(fake_stores["pipeline"].save(Pipeline(
            id="v_slow", name="v_slow", sources=["docs"], steps=_steps(),
            output_id=None, pipeline_type="eval",
        )))
        rid = _run(fake_stores["run"].create("v_slow"))
        _run(fake_stores["run"].update(
            rid, status="running", eval_set_id="invoices_set", sweep_id="sw1"))
        assert client.get("/api/sweeps/sw1/comparison").json()["pending"] == 1

    def test_labels_summary_is_present_with_none_collected(self, client):
        body = client.get("/api/sweeps/sw1/comparison").json()
        assert body["labels"]["total"] == 0


class TestRejections:
    def test_unknown_sweep_404s(self, client):
        assert client.get("/api/sweeps/nope/comparison").status_code == 404

    def test_a_sweep_with_no_eval_set_is_refused(self, client, fake_stores):
        _run(fake_stores["pipeline"].save(Pipeline(
            id="loose", name="loose", sources=["docs"], steps=_steps(),
            output_id=None, pipeline_type="eval",
        )))
        rid = _run(fake_stores["run"].create("loose"))
        _run(fake_stores["run"].update(rid, status="completed", sweep_id="sw2"))
        r = client.get("/api/sweeps/sw2/comparison")
        assert r.status_code == 422
        assert "eval set" in r.json()["detail"]
