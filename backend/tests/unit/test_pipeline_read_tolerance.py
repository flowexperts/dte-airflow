"""Strict in, lenient out — one row from the future must not kill the list.

A pipeline written by a newer build (or by a branch since rolled back)
carries an op this code does not know. That was validated on the *read*
path too, so the row raised inside FastAPI's response validation and took
down `GET /api/pipelines` entirely — every other pipeline vanished with it,
and the only symptom was a 500 naming a step index. Version skew is normal;
losing the whole collection to one row is not.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dte.api.deps import get_pipeline_store
from dte.api.main import app
from dte.models.pipeline import Pipeline, PipelineBase
from tests.fakes import FakePipelineStore

_FUTURE_STEP = {"op": "op_from_a_later_release", "shape": {"unknown": True}}


def _kwargs(steps, pid="p1"):
    return dict(
        id=pid, name=pid,
        sources=[{"source_id": "s", "alias": "s"}],
        steps=steps, output_id="o",
    )


@pytest.fixture
def client_with(monkeypatch):
    def _make(pipelines):
        store = FakePipelineStore()
        for p in pipelines:
            asyncio.get_event_loop().run_until_complete(store.save(p))
        app.dependency_overrides[get_pipeline_store] = lambda: store
        return TestClient(app)
    yield _make
    app.dependency_overrides.clear()


def test_list_survives_a_pipeline_with_an_unknown_op(client_with):
    """The reported failure: `('response', 1)` — the *second* pipeline was
    unreadable and all of them disappeared."""
    c = client_with([
        Pipeline(**_kwargs([{"op": "rename", "mappings": {}}], pid="fine")),
        Pipeline(**_kwargs([_FUTURE_STEP], pid="from_the_future")),
    ])
    r = c.get("/api/pipelines")
    assert r.status_code == 200, r.text
    assert {p["id"] for p in r.json()} == {"fine", "from_the_future"}


def test_get_one_survives_too(client_with):
    c = client_with([Pipeline(**_kwargs([_FUTURE_STEP], pid="from_the_future"))])
    r = c.get("/api/pipelines/from_the_future")
    assert r.status_code == 200, r.text
    assert r.json()["steps"] == [_FUTURE_STEP]


def test_writing_an_unknown_op_is_still_rejected():
    """POST/PUT bind PipelineBase — the guard that matters is untouched."""
    with pytest.raises(ValidationError):
        PipelineBase(**_kwargs([_FUTURE_STEP]))


def test_writing_a_bad_config_for_a_known_op_is_still_rejected():
    with pytest.raises(ValidationError):
        PipelineBase(**_kwargs([{"op": "retype", "field": "a", "to_type": "nonsense"}]))


def test_a_step_that_is_not_a_step_is_still_corruption(client_with):
    """Lenient about *which* op, not about whether it is a step at all."""
    for broken in (["not a dict"], [{"no_op_key": 1}]):
        with pytest.raises(ValidationError):
            PipelineBase(**_kwargs(broken))
