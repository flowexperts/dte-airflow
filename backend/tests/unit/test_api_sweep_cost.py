"""Sweep pre-flight cost estimate (plan 051).

The plan asks the pre-flight to return `est_cost_usd`. Nothing can know the
token count of a call that has not happened, so the estimate is derived
from what previous runs of this config actually spent, per document — a
measurement extrapolated, not a number invented.

With no prior run there is no basis, and the endpoint says so with `null`
rather than producing a figure. A launcher that quotes a confident price it
made up is worse than one that admits it doesn't know yet: the first gets
budgeted against.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.eval import EvalExampleBase, EvalSetBase
from dte.models.pipeline import SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="sc_src", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="sc_set", name="Invoices", source_id="sc_src",
        field_specs=[{"name": "total", "type": "numeric"}],
    )))
    for i in range(4):
        _run(fake_stores["eval_example"].save(EvalExampleBase(
            id="", eval_set_id="sc_set", doc_key=f"{i}" * 64,
            labels={"total": "1"}, label_source="human", split="train",
        )))
    assert c.post("/api/pipelines", json={
        "id": "sc_base", "name": "sc base", "sources": ["sc_src"], "output_id": None,
        "pipeline_type": "eval",
        "steps": [
            {"op": "extract", "source_field": "path", "provider": "pdfplumber",
             "granularity": "page", "output_field": "content", "params": {}},
            {"op": "structure", "input_field": "content", "provider": "claude",
             "on_error": "null", "params": {"model": "claude-opus-5"},
             "model": {"instructions": "b", "fields": [
                 {"name": "total", "type": "string", "required": False,
                  "description": "d"}]}},
        ],
    }).status_code == 200
    yield c, fake_stores


def _preflight(c):
    return c.post("/api/eval-sets/sc_set/sweep", json={
        "pipeline_id": "sc_base", "matrix": {"provider": ["claude", "openai"]},
    }).json()


def test_no_prior_run_means_no_estimate(client):
    """Null, with a reason. An invented figure gets budgeted against and is
    wrong where nobody can check it."""
    c, _ = client
    body = _preflight(c)
    assert body["est_cost_usd"] is None
    assert "cost_basis" in body


def test_a_prior_run_grounds_the_estimate_in_measured_spend(client):
    c, stores = client
    rid = _run(stores["run"].create("sc_base"))
    _run(stores["run"].update(
        rid, status="completed", eval_set_id="sc_set", labels_version=1,
        scores={
            "macro_f1": 1.0, "n": 4,
            # $2.00 across 4 documents = $0.50/doc.
            "throughput": {"cost_usd": 2.0, "n_calls": 4},
        },
    ))
    body = _preflight(c)
    # 2 cells x 4 documents x $0.50.
    assert body["est_cost_usd"] == pytest.approx(4.0)


def test_a_fully_cached_prior_run_does_not_claim_the_sweep_is_free(client):
    """A prior run that cost nothing because everything was cached says
    nothing about the price of configs that have never run. Treating $0 as
    the per-document rate would quote a free sweep that then bills."""
    c, stores = client
    rid = _run(stores["run"].create("sc_base"))
    _run(stores["run"].update(
        rid, status="completed", eval_set_id="sc_set", labels_version=1,
        scores={"macro_f1": 1.0, "n": 4,
                "throughput": {"cost_usd": 0.0, "n_calls": 0}},
    ))
    body = _preflight(c)
    assert body["est_cost_usd"] is None


def test_an_unpriced_prior_run_yields_no_estimate(client):
    c, stores = client
    rid = _run(stores["run"].create("sc_base"))
    _run(stores["run"].update(
        rid, status="completed", eval_set_id="sc_set", labels_version=1,
        scores={"macro_f1": 1.0, "n": 4,
                "throughput": {"cost_usd": None, "n_calls": 4}},
    ))
    assert _preflight(c)["est_cost_usd"] is None
