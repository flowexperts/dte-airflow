"""Binding a schedule to an eval set (plan 051 phase 5).

Regression detection was already written and Wilson-gated, but it was
unreachable: `_run_body` reads `eval_set_id` off the run row, the trigger
route puts it there, and the ticker had no way to. A scheduled eval run
therefore failed every night with "eval pipeline triggered without an
eval_set_id" — the nightly drift check, which is the single most valuable
thing this harness can do, silently never worked.

The validation rules here are deliberately the *same* rules the trigger
route enforces. A schedule is a trigger on a timer; if the two paths
disagree about what a valid eval run looks like, one of them is wrong at
2am, when nobody is watching.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.eval import EvalSetBase
from dte.models.pipeline import DestinationCreate, SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="ev_src", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["destination"].save(DestinationCreate(
        id="ev_dst", connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/ev_out.json"},
    )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="ev_set", name="Invoices", source_id="ev_src",
        field_specs=[{"name": "total", "type": "numeric"}],
    )))

    # An eval pipeline (no destination) and an ordinary transform one, so
    # the cross-type rules have both sides to test against.
    assert c.post("/api/pipelines", json={
        "id": "ev_pipe", "name": "ev_pipe", "sources": ["ev_src"],
        "steps": [
            {"op": "extract", "source_field": "path", "provider": "pdfplumber",
             "granularity": "page", "output_field": "content", "params": {}},
            {"op": "structure", "input_field": "content", "provider": "regex",
             "on_error": "null", "params": {},
             "model": {"instructions": "", "fields": [
                 {"name": "total", "type": "string", "required": False,
                  "description": "the total", "pattern": r"Total: \$([\d,.]+)"}]}},
        ], "output_id": None, "pipeline_type": "eval",
    }).status_code == 200
    assert c.post("/api/pipelines", json={
        "id": "tx_pipe", "name": "tx_pipe", "sources": ["ev_src"],
        "steps": [], "output_id": "ev_dst",
    }).status_code == 200
    yield c, fake_stores


def _body(**overrides):
    base = {"cron_expr": "0 2 * * *", "timezone": "UTC"}
    base.update(overrides)
    return base


def test_eval_schedule_carries_the_eval_set_id(client):
    c, _ = client
    r = c.post("/api/pipelines/ev_pipe/schedules",
               json=_body(eval_set_id="ev_set"))
    assert r.status_code == 200, r.text
    assert r.json()["eval_set_id"] == "ev_set"


def test_eval_schedule_without_an_eval_set_is_rejected_at_save(client):
    """The whole point of validating here: a schedule that cannot produce a
    scoreable run must fail when the human is present to read the error,
    not once a night forever."""
    c, _ = client
    r = c.post("/api/pipelines/ev_pipe/schedules", json=_body())
    assert r.status_code == 422, r.text
    assert "eval_set_id" in str(r.json()["detail"])


def test_eval_set_id_on_a_transform_schedule_is_rejected(client):
    c, _ = client
    r = c.post("/api/pipelines/tx_pipe/schedules",
               json=_body(eval_set_id="ev_set"))
    assert r.status_code == 422, r.text


def test_unknown_eval_set_is_rejected_at_save(client):
    c, _ = client
    r = c.post("/api/pipelines/ev_pipe/schedules",
               json=_body(eval_set_id="no_such_set"))
    assert r.status_code == 422, r.text


def test_update_preserves_and_revalidates_the_eval_set(client):
    c, _ = client
    sid = c.post("/api/pipelines/ev_pipe/schedules",
                 json=_body(eval_set_id="ev_set")).json()["id"]

    r = c.put(f"/api/schedules/{sid}",
              json=_body(cron_expr="0 3 * * *", eval_set_id="ev_set"))
    assert r.status_code == 200, r.text
    assert r.json()["eval_set_id"] == "ev_set"

    # Dropping it on update must fail the same way create does — otherwise
    # an edit is a back door to the exact broken state create rejects.
    r = c.put(f"/api/schedules/{sid}", json=_body(cron_expr="0 3 * * *"))
    assert r.status_code == 422, r.text


def test_deleting_an_eval_set_a_schedule_uses_is_refused(client):
    """Matches the sources/destinations convention: 409 naming the
    referrers, rather than cascading a schedule out from under the user or
    leaving one pointed at nothing."""
    c, _ = client
    sid = c.post("/api/pipelines/ev_pipe/schedules",
                 json=_body(eval_set_id="ev_set")).json()["id"]

    r = c.delete("/api/eval-sets/ev_set")
    assert r.status_code == 409, r.text
    assert sid in str(r.json()["detail"])

    c.delete(f"/api/schedules/{sid}")
    assert c.delete("/api/eval-sets/ev_set").status_code == 204
