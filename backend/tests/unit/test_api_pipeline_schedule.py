"""One pipeline, one schedule, one DAG (plan 068).

The schedule is part of the pipeline spec: `GET/PUT/DELETE
/api/pipelines/{id}/schedule` edit `pipeline.schedule`, and every change
records a pipeline revision, because a revision is what becomes an Airflow
DAG version. Cron, params and eval-set rules are still checked at save
time, not at 2am.
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


TX = {"id": "tx_pipe", "name": "tx_pipe", "sources": ["ev_src"], "steps": [], "output_id": "ev_dst"}


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
    assert c.post("/api/pipelines", json=TX).status_code == 200
    yield c, fake_stores


def _body(**overrides):
    return {"cron_expr": "0 2 * * *", "timezone": "UTC", **overrides}


def _put(c, pid="tx_pipe", **kw):
    return c.put(f"/api/pipelines/{pid}/schedule", json=_body(**kw))


def test_set_get_delete(client):
    c, _ = client
    assert c.get("/api/pipelines/tx_pipe/schedule").json() is None
    r = _put(c)
    assert r.status_code == 200, r.text
    assert r.json()["cron_expr"] == "0 2 * * *" and r.json()["overlap"] == "skip"
    assert r.json()["next_run_at"]
    assert _put(c, cron_expr="0 5 * * *").json()["cron_expr"] == "0 5 * * *"  # replace, not add
    assert c.get("/api/pipelines/tx_pipe").json()["schedule"]["cron_expr"] == "0 5 * * *"
    assert c.delete("/api/pipelines/tx_pipe/schedule").status_code == 204
    assert c.get("/api/pipelines/tx_pipe/schedule").json() is None


def test_disabled_has_no_next_run(client):
    assert _put(client[0], enabled=False).json()["next_run_at"] is None


def test_missing_pipeline_404(client):
    c, _ = client
    assert _put(c, "nope").status_code == 404
    assert c.get("/api/pipelines/nope/schedule").status_code == 404
    assert c.delete("/api/pipelines/nope/schedule").status_code == 404


@pytest.mark.parametrize("kw,code", [
    ({"cron_expr": "not a cron"}, "invalid_cron_expression"),
    ({"timezone": "Not/AZone"}, "invalid_timezone"),
    ({"params": {"region": "us"}}, "param_validation_error"),
])
def test_bad_schedule_422(client, kw, code):
    r = _put(client[0], **kw)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code


def test_missing_required_param_422(client):
    c, _ = client
    assert c.put("/api/pipelines/tx_pipe", json={
        **TX, "params": [{"name": "region", "type": "string", "required": True}],
    }).status_code == 200
    r = _put(c)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "param_validation_error"


def test_pipeline_put_validates_schedule_too(client):
    """The schedule rides the pipeline body, so the pipeline PUT is a second
    way in — it must not be a back door past the same checks."""
    r = client[0].put("/api/pipelines/tx_pipe", json={**TX, "schedule": _body(cron_expr="nope")})
    assert r.status_code == 422


def test_pipeline_put_without_schedule_keeps_it(client):
    """The builder saves steps without knowing about the schedule; that save
    must not silently unschedule the pipeline."""
    c, _ = client
    _put(c)
    assert c.put("/api/pipelines/tx_pipe", json={**TX, "name": "renamed"}).status_code == 200
    assert c.get("/api/pipelines/tx_pipe/schedule").json()["cron_expr"] == "0 2 * * *"
    assert c.put("/api/pipelines/tx_pipe", json={**TX, "schedule": None}).status_code == 200
    assert c.get("/api/pipelines/tx_pipe/schedule").json() is None


def test_schedule_change_records_a_revision(client):
    """Revision = DAG version: a schedule edit changes the DAG, so it must
    be a revision too."""
    c, stores = client
    revs = stores["pipeline_revision"]
    before = _run(revs.count_for_pipeline("tx_pipe"))
    _put(c)
    latest = _run(revs.latest_for_pipeline("tx_pipe"))
    assert _run(revs.count_for_pipeline("tx_pipe")) == before + 1
    assert latest.config["schedule"]["cron_expr"] == "0 2 * * *"
    c.delete("/api/pipelines/tx_pipe/schedule")
    assert _run(revs.latest_for_pipeline("tx_pipe")).config["schedule"] is None


def test_eval_schedule_rules(client):
    """Same rules the trigger route enforces: a schedule is a trigger on a timer."""
    c, _ = client
    assert _put(c, "ev_pipe").status_code == 422                                   # needs a corpus
    assert _put(c, "tx_pipe", eval_set_id="ev_set").status_code == 422              # transform can't have one
    assert _put(c, "ev_pipe", eval_set_id="no_such_set").status_code == 422
    r = _put(c, "ev_pipe", eval_set_id="ev_set")
    assert r.status_code == 200 and r.json()["eval_set_id"] == "ev_set"


def test_deleting_a_scheduled_eval_set_is_refused(client):
    c, _ = client
    _put(c, "ev_pipe", eval_set_id="ev_set")
    r = c.delete("/api/eval-sets/ev_set")
    assert r.status_code == 409 and "ev_pipe" in str(r.json()["detail"])
    c.delete("/api/pipelines/ev_pipe/schedule")
    assert c.delete("/api/eval-sets/ev_set").status_code == 204


def test_promoted_pipeline_has_a_revision(client):
    """Every saved pipeline is a DAG, and a DAG runs a revision — so a
    pipeline created outside the builder needs one too."""
    c, stores = client
    r = c.post("/api/eval-sets/ev_set/promote", json={
        "pipeline_id": "ev_pipe", "new_pipeline_id": "promoted", "name": "promoted",
        "output_id": "ev_dst",
    })
    assert r.status_code == 201, r.text
    assert _run(stores["pipeline_revision"].latest_for_pipeline("promoted")) is not None


def test_trigger_pins_the_latest_revision(client):
    c, stores = client
    _put(c)
    rid = c.post("/api/pipelines/tx_pipe/trigger", json={}).json()["run_id"]
    latest = _run(stores["pipeline_revision"].latest_for_pipeline("tx_pipe"))
    assert _run(stores["run"].get(rid))["revision_id"] == latest.id


def test_failure_settings_round_trip(client):
    """Plan 070: retries and timeout ride the schedule."""
    r = _put(client[0], retries=2, retry_delay_s=60, timeout_s=600)
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in ("retries", "retry_delay_s", "timeout_s")} == {
        "retries": 2, "retry_delay_s": 60, "timeout_s": 600}
    assert _put(client[0], retries=11).status_code == 422


def test_retries_refused_on_append_destination(client):
    """A retry after a partial append writes the rows twice."""
    from dte.models.pipeline import Pipeline
    c, stores = client
    _run(stores["destination"].save(DestinationCreate(
        id="ap_dst", connection_id="local_fs",
        config={"type": "postgres", "schema": "public", "table": "t", "write_disposition": "append"},
    )))
    _run(stores["pipeline"].save(Pipeline(**{**TX, "id": "ap_pipe", "name": "ap_pipe", "output_id": "ap_dst"})))
    r = _put(c, "ap_pipe", retries=1)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "retries_on_append"
    assert _put(c, "ap_pipe").status_code == 200       # no retries: fine
    assert _put(c, retries=1).status_code == 200       # replace destination: fine
