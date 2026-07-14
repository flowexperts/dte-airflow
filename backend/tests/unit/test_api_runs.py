import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import (
    get_run_store, get_pipeline_store, get_destination_store,
)
from dte.store.memory import (
    MemoryRunStore, MemoryPipelineStore, MemoryDestinationStore,
)


@pytest.fixture
def client():
    r_store = MemoryRunStore()
    app.dependency_overrides[get_run_store] = lambda: r_store
    yield TestClient(app), r_store
    app.dependency_overrides.clear()


@pytest.fixture
def output_client():
    r_store = MemoryRunStore()
    p_store = MemoryPipelineStore()
    d_store = MemoryDestinationStore()
    app.dependency_overrides[get_run_store] = lambda: r_store
    app.dependency_overrides[get_pipeline_store] = lambda: p_store
    app.dependency_overrides[get_destination_store] = lambda: d_store
    yield TestClient(app), r_store, p_store, d_store
    app.dependency_overrides.clear()


def _pipeline(pid: str, output_id: str = "out1") -> dict:
    return {
        "id": pid, "name": pid,
        "sources": ["s1"], "steps": [], "output_id": output_id,
    }


def _destination(dest_id: str, config: dict) -> dict:
    return {"id": dest_id, "config": config}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_list_runs_empty(client):
    c, _ = client
    r = c.get("/api/pipelines/p1/runs")
    assert r.status_code == 200
    assert r.json() == []


def test_list_runs_returns_own_pipeline_only(client):
    c, store = client
    _run(store.create("p1"))
    _run(store.create("p1"))
    _run(store.create("p2"))

    r = c.get("/api/pipelines/p1/runs")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert all(row["pipeline_id"] == "p1" for row in body)

    r = c.get("/api/pipelines/p2/runs")
    assert len(r.json()) == 1


def test_list_runs_limit(client):
    c, store = client
    for _ in range(5):
        _run(store.create("p1"))

    r = c.get("/api/pipelines/p1/runs?limit=3")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_run_has_started_at_on_create(client):
    c, store = client
    run_id = _run(store.create("p1"))

    r = c.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["started_at"] is not None
    assert body["finished_at"] is None


def test_run_finished_at_set_on_completion(client):
    c, store = client
    run_id = _run(store.create("p1"))
    _run(store.update(run_id, status="completed", rows_written=42))
    from datetime import datetime, timezone
    _run(store.update(run_id, finished_at=datetime.now(timezone.utc).isoformat()))

    r = c.get(f"/api/runs/{run_id}")
    body = r.json()
    assert body["status"] == "completed"
    assert body["finished_at"] is not None


def test_list_runs_includes_timestamps(client):
    c, store = client
    _run(store.create("p1"))
    r = c.get("/api/pipelines/p1/runs")
    body = r.json()
    assert "started_at" in body[0]
    assert "finished_at" in body[0]


def test_output_returns_first_rows_for_json_file(tmp_path, output_client):
    c, r_store, p_store, d_store = output_client
    out_path = tmp_path / "out.json"
    rows = [{"n": i} for i in range(10)]
    out_path.write_text(json.dumps(rows))

    _run(d_store.save(_destination("out1", {"type": "json_file", "path": str(out_path)})))
    _run(p_store.save(_pipeline("p1")))
    run_id = _run(r_store.create("p1"))
    _run(r_store.update(run_id, status="completed", rows_written=10, location=str(out_path)))

    r = c.get(f"/api/runs/{run_id}/output?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 5
    assert body["rows"] == rows[:5]


def test_output_unknown_run_returns_404(output_client):
    c, *_ = output_client
    r = c.get("/api/runs/does-not-exist/output")
    assert r.status_code == 404


def test_output_pending_run_returns_400(output_client):
    c, r_store, p_store, d_store = output_client
    _run(d_store.save(_destination("out1", {"type": "json_file", "path": "/tmp/x.json"})))
    _run(p_store.save(_pipeline("p1")))
    run_id = _run(r_store.create("p1"))
    r = c.get(f"/api/runs/{run_id}/output")
    assert r.status_code == 400


def test_output_missing_location_returns_400(output_client):
    c, r_store, p_store, d_store = output_client
    _run(d_store.save(_destination("out1", {"type": "json_file", "path": "/tmp/x.json"})))
    _run(p_store.save(_pipeline("p1")))
    run_id = _run(r_store.create("p1"))
    _run(r_store.update(run_id, status="completed", rows_written=0))
    r_store._data[run_id]["location"] = None
    r = c.get(f"/api/runs/{run_id}/output")
    assert r.status_code == 400


def test_output_unsupported_target_returns_400(tmp_path, output_client):
    c, r_store, p_store, d_store = output_client
    output = {
        "type": "postgres",
        "credentials": "postgresql://x",
        "schema": "public",
        "table": "t",
    }
    _run(d_store.save(_destination("out1", output)))
    _run(p_store.save(_pipeline("p1")))
    run_id = _run(r_store.create("p1"))
    _run(r_store.update(run_id, status="completed", rows_written=1, location="tcp://ignored"))

    r = c.get(f"/api/runs/{run_id}/output")
    assert r.status_code == 400
    assert "postgres" in r.json()["detail"]
