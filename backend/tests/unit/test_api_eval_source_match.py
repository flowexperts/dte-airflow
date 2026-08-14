"""An eval run must read the corpus its labels describe (plan 051).

Labels join to extracted rows by `doc_key` — the sha256 of the document.
Score a pipeline that reads a *different* documents source and every hash
misses: no row matches any label, and the run completes green having
measured nothing. Depending on the corpus it reports n=0 or a flat zero,
and both read as "the extractor is broken".

This is the same silent-zero failure as binding an eval set to the wrong
source kind, one level along: there the corpus could never produce hashes,
here it produces the wrong ones. Neither raises on its own, so both are
refused at the edge.
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
             {"name": "total", "type": "string", "required": False,
              "description": "the total", "pattern": r"(\d+)"}]}},
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
    for pid, src in (("pipe_a", "docs_a"), ("pipe_b", "docs_b")):
        _run(fake_stores["pipeline"].save(Pipeline(
            id=pid, name=pid, sources=[src], steps=_steps(),
            output_id=None, pipeline_type="eval",
        )))
    return c


def _trigger(c, pipeline_id, eval_set_id="set_a"):
    return c.post(f"/api/pipelines/{pipeline_id}/trigger",
                  json={"eval_set_id": eval_set_id})


def test_a_pipeline_reading_the_sets_corpus_is_allowed(client):
    assert _trigger(client, "pipe_a").status_code == 200


def test_a_pipeline_reading_a_different_corpus_is_refused(client):
    r = _trigger(client, "pipe_b")
    assert r.status_code == 422


def test_the_refusal_names_both_sources(client):
    """"Sources don't match" sends someone to compare two configs by hand.
    Naming what the set expects and what the pipeline reads makes the fix
    obvious from the message alone."""
    body = _trigger(client, "pipe_b").text
    assert "docs_a" in body
    assert "docs_b" in body


def test_the_corpus_may_be_one_of_several_sources(client):
    """The rule is that the labeled corpus is *present*, not that it is the
    only source. A pipeline joining a lookup alongside the documents is
    still scoring the right documents."""
    _run(client.app.dependency_overrides and asyncio.sleep(0))
    from dte.api.deps import get_pipeline_store
    store = app.dependency_overrides[get_pipeline_store]()
    _run(store.save(Pipeline(
        id="pipe_multi", name="multi", sources=["docs_b", "docs_a"],
        steps=_steps(), output_id=None, pipeline_type="eval",
    )))
    assert _trigger(client, "pipe_multi").status_code == 200
