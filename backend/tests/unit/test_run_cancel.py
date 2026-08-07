"""POST /api/runs/{id}/cancel (plan 046 task 9).

`dte/runs.py`'s process-local `run_registry` is replaced by queue-native
cancel for distributed (job_id-carrying) runs: procrastinate's
`cancel_job_by_id_async(job_id, abort=True)` works regardless of which
worker pod picked the job up. Flag-off runs (no job_id — the in-process
asyncio.create_task path) keep an equivalent process-local registry, now
private to dte.api.routes.pipelines instead of a shared dte.runs module.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores):
    return TestClient(app), fake_stores


def test_cancel_run_not_found_404(client):
    c, _ = client
    r = c.post("/api/runs/does-not-exist/cancel")
    assert r.status_code == 404


def test_cancel_run_already_terminal_409(client):
    c, stores = client

    async def _seed():
        run_id = await stores["run"].create("p1")
        await stores["run"].update(run_id, status="completed")
        return run_id

    run_id = _run(_seed())
    r = c.post(f"/api/runs/{run_id}/cancel")
    assert r.status_code == 409


def test_cancel_run_flag_off_cancels_local_task(client):
    """No job_id on the run → process-local registry path. Cancelling
    actually cancels the asyncio task (not just a DB status flip)."""
    import dte.api.routes.pipelines as pipelines_mod

    c, stores = client

    async def _seed():
        run_id = await stores["run"].create("p1")
        await stores["run"].update(run_id, status="running")
        return run_id

    run_id = _run(_seed())

    async def _spawn_and_register():
        task = asyncio.ensure_future(asyncio.sleep(30))
        pipelines_mod._register_local_task(run_id, task)
        return task

    task = _run(_spawn_and_register())

    r = c.post(f"/api/runs/{run_id}/cancel")
    assert r.status_code == 200, r.text
    assert r.json() == {"cancelled": True}
    assert task.cancelled() or task.cancel()  # actually requested cancellation


def test_cancel_run_flag_off_no_local_task_marks_failed(client):
    c, stores = client

    async def _seed():
        run_id = await stores["run"].create("p1")
        await stores["run"].update(run_id, status="running")
        return run_id

    run_id = _run(_seed())

    r = c.post(f"/api/runs/{run_id}/cancel")
    assert r.status_code == 200, r.text
    assert r.json()["cancelled"] is False
    run = _run(stores["run"].get(run_id))
    assert run["status"] == "failed"


def test_cancel_run_job_queue_cancels_via_procrastinate(client, monkeypatch):
    """A run with job_id set uses queue-native cancel — no process-local
    state consulted at all."""
    import dte.worker.app as worker_app_mod

    c, stores = client
    calls = []

    class _FakeJobManager:
        async def cancel_job_by_id_async(self, job_id, abort=False):
            calls.append((job_id, abort))
            return True

    class _FakeApp:
        job_manager = _FakeJobManager()

    async def fake_get_running_app():
        return _FakeApp()

    monkeypatch.setattr(worker_app_mod, "get_running_app", fake_get_running_app)

    async def _seed():
        run_id = await stores["run"].create("p1")
        await stores["run"].update(run_id, status="running", job_id=42)
        return run_id

    run_id = _run(_seed())

    r = c.post(f"/api/runs/{run_id}/cancel")

    assert r.status_code == 200, r.text
    assert r.json() == {"cancelled": True}
    assert calls == [(42, True)]


def test_cancel_run_job_queue_job_already_finished(client, monkeypatch):
    import dte.worker.app as worker_app_mod

    c, stores = client

    class _FakeJobManager:
        async def cancel_job_by_id_async(self, job_id, abort=False):
            return False

    class _FakeApp:
        job_manager = _FakeJobManager()

    async def fake_get_running_app():
        return _FakeApp()

    monkeypatch.setattr(worker_app_mod, "get_running_app", fake_get_running_app)

    async def _seed():
        run_id = await stores["run"].create("p1")
        await stores["run"].update(run_id, status="running", job_id=99)
        return run_id

    run_id = _run(_seed())

    r = c.post(f"/api/runs/{run_id}/cancel")

    assert r.status_code == 200, r.text
    assert r.json()["cancelled"] is False
    run = _run(stores["run"].get(run_id))
    assert run["status"] == "failed"


def test_dte_runs_module_removed():
    with pytest.raises(ModuleNotFoundError):
        import dte.runs  # noqa: F401
