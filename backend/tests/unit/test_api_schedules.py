"""Schedule CRUD API (plan 047 task 3).

Create/update validate cron + params up front ("params validated at
create time, not at 2am" — plan 047) so a schedule with a bad cron or a
missing required param never gets persisted to fire silently at 2am.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import DestinationCreate, SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    s_store = fake_stores["source"]
    d_store = fake_stores["destination"]
    _run(s_store.save(SourceCreate(
        id="sch_src", connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": "/tmp"}, table="dummy",
    )))
    _run(d_store.save(DestinationCreate(
        id="sch_dst", connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/sch_out.json"},
    )))
    r = c.post("/api/pipelines", json={
        "id": "sch_pipeline", "name": "sch_pipeline",
        "sources": ["sch_src"], "steps": [], "output_id": "sch_dst",
    })
    assert r.status_code == 200, r.text
    yield c, fake_stores


def _body(**overrides):
    base = {"cron_expr": "0 2 * * *", "timezone": "UTC"}
    base.update(overrides)
    return base


def test_create_schedule_success(client):
    c, stores = client
    r = c.post("/api/pipelines/sch_pipeline/schedules", json=_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pipeline_id"] == "sch_pipeline"
    assert body["cron_expr"] == "0 2 * * *"
    assert body["enabled"] is True
    assert body["overlap"] == "skip"
    assert body["next_run_at"] is not None


def test_create_schedule_missing_pipeline_404(client):
    c, _ = client
    r = c.post("/api/pipelines/does-not-exist/schedules", json=_body())
    assert r.status_code == 404


def test_create_schedule_bad_cron_422(client):
    c, _ = client
    r = c.post("/api/pipelines/sch_pipeline/schedules", json=_body(cron_expr="not a cron"))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_cron_expression"


def test_create_schedule_bad_timezone_422(client):
    c, _ = client
    r = c.post("/api/pipelines/sch_pipeline/schedules", json=_body(timezone="Not/AZone"))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_timezone"


def test_create_schedule_unknown_param_422(client):
    c, _ = client
    r = c.post(
        "/api/pipelines/sch_pipeline/schedules",
        json=_body(params={"region": "us"}),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "param_validation_error"


def test_create_schedule_missing_required_param_422(client):
    c, stores = client
    r = c.put("/api/pipelines/sch_pipeline", json={
        "id": "sch_pipeline", "name": "sch_pipeline",
        "sources": ["sch_src"], "steps": [], "output_id": "sch_dst",
        "params": [{"name": "region", "type": "string", "required": True}],
    })
    assert r.status_code == 200, r.text

    r = c.post("/api/pipelines/sch_pipeline/schedules", json=_body())
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "param_validation_error"


def test_create_schedule_disabled_has_no_next_run_at(client):
    c, _ = client
    r = c.post("/api/pipelines/sch_pipeline/schedules", json=_body(enabled=False))
    assert r.status_code == 200, r.text
    assert r.json()["next_run_at"] is None


def test_list_schedules_for_pipeline(client):
    c, _ = client
    c.post("/api/pipelines/sch_pipeline/schedules", json=_body())
    c.post("/api/pipelines/sch_pipeline/schedules", json=_body(cron_expr="0 3 * * *"))
    r = c.get("/api/pipelines/sch_pipeline/schedules")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_get_schedule(client):
    c, _ = client
    created = c.post("/api/pipelines/sch_pipeline/schedules", json=_body()).json()
    r = c.get(f"/api/schedules/{created['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == created["id"]


def test_get_schedule_missing_404(client):
    c, _ = client
    r = c.get("/api/schedules/does-not-exist")
    assert r.status_code == 404


def test_update_schedule(client):
    c, _ = client
    created = c.post("/api/pipelines/sch_pipeline/schedules", json=_body()).json()
    r = c.put(f"/api/schedules/{created['id']}", json=_body(cron_expr="0 5 * * *"))
    assert r.status_code == 200, r.text
    assert r.json()["cron_expr"] == "0 5 * * *"
    # next_run_at is recomputed against the new cron.
    assert r.json()["next_run_at"] is not None


def test_update_schedule_missing_404(client):
    c, _ = client
    r = c.put("/api/schedules/does-not-exist", json=_body())
    assert r.status_code == 404


def test_update_schedule_bad_cron_422(client):
    c, _ = client
    created = c.post("/api/pipelines/sch_pipeline/schedules", json=_body()).json()
    r = c.put(f"/api/schedules/{created['id']}", json=_body(cron_expr="nope"))
    assert r.status_code == 422


def test_delete_schedule(client):
    c, _ = client
    created = c.post("/api/pipelines/sch_pipeline/schedules", json=_body()).json()
    r = c.delete(f"/api/schedules/{created['id']}")
    assert r.status_code == 204
    assert c.get(f"/api/schedules/{created['id']}").status_code == 404


def test_delete_schedule_missing_404(client):
    c, _ = client
    r = c.delete("/api/schedules/does-not-exist")
    assert r.status_code == 404
