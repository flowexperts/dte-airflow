"""`POST /api/eval-sets/{id}/sweep` (plan 051 phase 4).

The endpoint previously returned `enqueued: true` with a list of cells and
started nothing. That is the worst shape this feature can take: the caller
is told it worked, no money is spent, no runs appear, and the leaderboard
stays empty in a way that reads as "every config failed" rather than
"nothing ran". These tests pin that a confirmed sweep produces real
pipelines and real runs.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.eval import EvalSetBase
from dte.models.pipeline import SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores, monkeypatch):
    # Runs are started for real by the endpoint; executing them would need
    # PDFs and providers. Patch the executor, not the enqueue path, so the
    # run rows and their eval identity are still written exactly as in
    # production.
    async def fake_execute(*a, **kw):
        return None

    import dte.worker.tasks as tasks
    monkeypatch.setattr(tasks, "_execute_pipeline", fake_execute)

    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="sw_src", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="sw_set", name="Invoices", source_id="sw_src",
        field_specs=[{"name": "total", "type": "numeric"}],
    )))
    assert c.post("/api/pipelines", json={
        "id": "sw_base", "name": "sw base", "sources": ["sw_src"], "output_id": None,
        "pipeline_type": "eval",
        "steps": [
            {"op": "extract", "source_field": "path", "provider": "pdfplumber",
             "granularity": "page", "output_field": "content", "params": {}},
            {"op": "structure", "input_field": "content", "provider": "regex",
             "on_error": "null", "params": {},
             "model": {"instructions": "base", "fields": [
                 {"name": "total", "type": "string", "required": False,
                  "description": "d", "pattern": "x"}]}},
        ],
    }).status_code == 200
    yield c, fake_stores


def test_preflight_enqueues_nothing(client):
    c, stores = client
    r = c.post("/api/eval-sets/sw_set/sweep", json={
        "pipeline_id": "sw_base",
        "matrix": {"provider": ["claude", "openai"]},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enqueued"] is False
    assert body["cells"] == 2
    assert _run(stores["run"].list_for_eval_set("sw_set", limit=50)) == []


def test_confirmed_sweep_creates_a_pipeline_and_a_run_per_cell(client):
    c, stores = client
    r = c.post("/api/eval-sets/sw_set/sweep", json={
        "pipeline_id": "sw_base",
        "matrix": {"provider": ["claude", "openai"]},
        "confirm": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enqueued"] is True
    assert len(body["runs"]) == 2
    # Every cell must carry a real run id — the leaderboard reads runs, and a
    # cell without one is a config that will never appear.
    assert all(run["run_id"] for run in body["runs"])

    for run in body["runs"]:
        assert _run(stores["pipeline"].get(run["pipeline_id"])) is not None

    runs = _run(stores["run"].list_for_eval_set("sw_set", limit=50))
    assert len(runs) == 2
    # One sweep_id ties the cells together; the eval set is what they score
    # against. Missing either breaks the grouping the leaderboard does.
    assert {r["sweep_id"] for r in runs} == {body["sweep_id"]}
    assert {r["eval_set_id"] for r in runs} == {"sw_set"}


def test_cells_get_distinct_pipelines(client):
    """Two cells collapsing onto one pipeline id would overwrite each other
    and report as a single leaderboard row — a 2-cell sweep rendering as
    one, with nothing to indicate the other was lost."""
    c, _ = client
    body = c.post("/api/eval-sets/sw_set/sweep", json={
        "pipeline_id": "sw_base",
        "matrix": {"provider": ["claude", "openai"]},
        "confirm": True,
    }).json()
    ids = {run["pipeline_id"] for run in body["runs"]}
    assert len(ids) == 2


def test_relaunching_the_same_sweep_reuses_the_variant_pipelines(client):
    """Deterministic ids: a re-run must land on the same rows, or every
    launch accumulates a fresh set of near-identical pipelines and pays the
    provider again for a config it already has cached."""
    c, stores = client
    payload = {
        "pipeline_id": "sw_base",
        "matrix": {"provider": ["claude"]},
        "confirm": True,
    }
    first = c.post("/api/eval-sets/sw_set/sweep", json=payload).json()
    second = c.post("/api/eval-sets/sw_set/sweep", json=payload).json()
    assert first["runs"][0]["pipeline_id"] == second["runs"][0]["pipeline_id"]
    # Two runs of one config, not two configs.
    assert first["sweep_id"] != second["sweep_id"]


def test_a_typo_in_the_matrix_is_rejected(client):
    """Silently ignoring an unknown axis produces N identical cells that all
    score the same, reading as 'this setting makes no difference'."""
    c, _ = client
    r = c.post("/api/eval-sets/sw_set/sweep", json={
        "pipeline_id": "sw_base",
        "matrix": {"provdier": ["claude", "openai"]},
        "confirm": True,
    })
    assert r.status_code == 422, r.text
    assert "provdier" in str(r.json()["detail"])


def test_a_transform_pipeline_cannot_be_swept(client):
    c, _ = client
    assert c.post("/api/pipelines", json={
        "id": "sw_tx", "name": "sw tx", "sources": ["sw_src"],
        "steps": [], "output_id": None, "pipeline_type": "quality",
    }).status_code == 200
    r = c.post("/api/eval-sets/sw_set/sweep",
               json={"pipeline_id": "sw_tx", "matrix": {"provider": ["claude"]}})
    assert r.status_code == 422, r.text
