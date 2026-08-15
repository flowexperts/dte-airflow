"""Tests for the plan-046 task-3 refactor: `_execute_pipeline` moves from
`dte.api.routes.pipelines` into `dte.worker.tasks`, verbatim. `_run_body`
stays put and unchanged — the module boundary is the only thing that
moves. With `DTE_JOB_QUEUE_ENABLED` off (default), the trigger endpoint's
external behaviour must be identical to before the refactor.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import DestinationCreate, SourceCreate

_TERMINAL = {"completed", "failed", "completed_with_warnings", "failed_quality", "cancelled"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_execute_pipeline_lives_in_worker_tasks_module():
    import dte.api.routes.pipelines as pipelines_mod
    import dte.worker.tasks as tasks_mod

    assert hasattr(tasks_mod, "_execute_pipeline")
    # The refactor removes the old in-module definition — pipelines.py
    # dispatches to the extracted function rather than redefining it.
    assert not hasattr(pipelines_mod, "_execute_pipeline")
    # _run_body is explicitly required to stay put, unchanged.
    assert hasattr(pipelines_mod, "_run_body")


def test_enqueue_run_lives_in_worker_tasks_module():
    """plan 047 task 4: enqueue_run (formerly _enqueue_run, private to
    pipelines.py) moves to dte.worker.tasks so the ticker
    (dte.worker.scheduler, task 5) can share it instead of duplicating the
    same-connection insert-then-defer dance."""
    import dte.api.routes.pipelines as pipelines_mod
    import dte.worker.tasks as tasks_mod

    assert hasattr(tasks_mod, "enqueue_run")
    assert not hasattr(pipelines_mod, "_enqueue_run")


def test_enqueue_run_accepts_tenant_id_and_schedule_id():
    import inspect

    from dte.worker.tasks import enqueue_run

    params = inspect.signature(enqueue_run).parameters
    assert list(params) == ["pipeline_id", "revision_id", "tenant_id", "schedule_id"]
    assert params["tenant_id"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["schedule_id"].default is None


def test_execute_pipeline_signature_unchanged():
    """The extracted function keeps the exact positional-arg contract the
    trigger endpoint (and any future queue payload) depends on."""
    import inspect

    from dte.worker.tasks import _execute_pipeline

    sig = inspect.signature(_execute_pipeline)
    positional = [
        name for name, p in sig.parameters.items()
        if p.kind is not inspect.Parameter.KEYWORD_ONLY
    ]
    assert positional == [
        "pipeline_id", "run_id", "p_store", "r_store", "re_store",
        "s_store", "d_store", "c_store", "lt_store",
    ]
    # Plan 051 added the eval stores. They are keyword-only and default to
    # None precisely so the positional contract above stays intact and every
    # existing caller keeps working untouched — which is what this test is
    # actually guarding.
    for name in ("es_store", "ee_store"):
        assert sig.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters[name].default is None


@pytest.fixture
def client(fake_stores, tmp_path):
    s_store = fake_stores["source"]
    d_store = fake_stores["destination"]
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "rows.json").write_text(json.dumps([{"a": 1}, {"a": 2}]))
    out_path = tmp_path / "out.json"
    _run(s_store.save(SourceCreate(
        id="wt_src", connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": str(src_dir)}, table="rows",
    )))
    _run(d_store.save(DestinationCreate(
        id="wt_dst", connection_id="local_fs",
        config={"type": "json_file", "path": str(out_path)},
    )))
    yield TestClient(app), fake_stores, out_path


def test_trigger_flag_off_completes_via_extracted_executor(client):
    """Regression: with the job queue flag off, trigger still resolves to
    the asyncio.create_task path, now calling the extracted executor, and
    the run reaches `completed`."""
    c, stores, out_path = client
    pipeline = {
        "id": "wt_pipeline", "name": "wt_pipeline",
        "sources": ["wt_src"], "steps": [], "output_id": "wt_dst",
    }
    r = c.post("/api/pipelines", json=pipeline)
    assert r.status_code == 200, r.text

    r = c.post("/api/pipelines/wt_pipeline/trigger")
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]

    run = None
    for _ in range(100):
        run = c.get(f"/api/runs/{run_id}").json()
        if run["status"] in _TERMINAL:
            break
        time.sleep(0.1)

    assert run is not None
    assert run["status"] == "completed", run
    assert run["rows_written"] == 2
    assert out_path.exists()
