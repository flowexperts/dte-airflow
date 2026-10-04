"""Pytest fixtures.

Autouse `fake_stores` attaches in-memory `Fake*Store` implementations to
the FastAPI app for every test. Individual tests that need to inspect or
seed a store still install their own override in a fixture — the autouse
just guarantees no test ever hits the real Postgres deps.

Autouse also short-circuits `get_current_user` to a fake user so existing
tests keep working without threading Authorization headers through every
request. Tests that specifically exercise the auth flow (login, 401 on
bad/missing token) opt out via
`app.dependency_overrides.pop(get_current_user, None)`.
"""
import json
import pytest

from dte.api.main import app
from dte.api.deps import (
    get_pipeline_revision_store,
    get_pipeline_store,
    get_run_event_store,
    get_run_store,
    get_source_store,
    get_destination_store,
    get_connection_store,
    get_current_user,
    get_current_tenant_id,
    get_dashboard_store,
    get_lookup_table_store,
    get_eval_example_store,
    get_eval_set_store,
)
from dte.models.pipeline import Connection
from dte.models.user import User
from tests.fakes import (
    FakePipelineRevisionStore,
    FakePipelineStore,
    FakeRunEventStore,
    FakeRunStore,
    FakeSourceStore,
    FakeDestinationStore,
    FakeConnectionStore,
    FakeDashboardStore,
    FakeLookupTableStore,
    FakeEvalExampleStore,
    FakeEvalSetStore,
)


def _make_local_fs_connection() -> Connection:
    """Build the pre-seeded local_fs Connection instance."""
    return Connection(id="local_fs", connection_type="local_fs", credentials={})


def _fake_test_user() -> User:
    from dte.security.permissions import ALL_PERMISSIONS
    return User(id="test-user", email="test@example.com", permissions=list(ALL_PERMISSIONS))


@pytest.fixture(autouse=True)
def _isolated_artifact_dir(tmp_path, monkeypatch):
    """Point the extract cache at tmp_path for every test.

    `DEFAULT_ARTIFACT_DIR` is the relative `.dte-artifacts`, which resolves
    against the CWD — so an unguarded suite run drops a cache directory into
    `backend/` and, worse, shares it between tests. A per-test directory also
    means cache-hit assertions start from a known-cold state.
    """
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path / "artifacts"))


@pytest.fixture(autouse=True)
def fake_stores():
    p, r, re, s, d, c, lt, pr = (
        FakePipelineStore(),
        FakeRunStore(),
        FakeRunEventStore(),
        FakeSourceStore(),
        FakeDestinationStore(),
        FakeConnectionStore(),
        FakeLookupTableStore(),
        FakePipelineRevisionStore(),
    )
    es, ee = FakeEvalSetStore(), FakeEvalExampleStore()
    dash = FakeDashboardStore()
    # Every test gets a `local_fs` connection pre-seeded — most sources /
    # destinations use it, tests don't have to re-declare it every time.
    c._data["local_fs"] = _make_local_fs_connection()
    app.dependency_overrides[get_pipeline_store] = lambda: p
    app.dependency_overrides[get_run_store] = lambda: r
    app.dependency_overrides[get_run_event_store] = lambda: re
    app.dependency_overrides[get_source_store] = lambda: s
    app.dependency_overrides[get_destination_store] = lambda: d
    app.dependency_overrides[get_connection_store] = lambda: c
    app.dependency_overrides[get_lookup_table_store] = lambda: lt
    app.dependency_overrides[get_dashboard_store] = lambda: dash
    app.dependency_overrides[get_pipeline_revision_store] = lambda: pr
    app.dependency_overrides[get_eval_set_store] = lambda: es
    app.dependency_overrides[get_eval_example_store] = lambda: ee
    # Bypass auth for existing tests — auth-flow tests opt out per-test.
    app.dependency_overrides[get_current_user] = lambda: _fake_test_user()
    # Bypass tenant_id dep — tests always use the "default" tenant.
    app.dependency_overrides[get_current_tenant_id] = lambda: "default"
    yield {
        "pipeline": p,
        "run": r,
        "run_event": re,
        "source": s,
        "destination": d,
        "connection": c,
        "lookup_table": lt,
        "dashboard": dash,
        "pipeline_revision": pr,
        "eval_set": es,
        "eval_example": ee,
    }
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fake_airflow_trigger(fake_stores, monkeypatch):
    """Triggering is an Airflow REST call; in tests it just records a run row
    in the fake run store, carrying what the dag run `conf` would."""
    import dte.airflow.trigger as trig

    async def _trigger(pipeline_id, conf, wait=0):
        r = fake_stores["run"]
        run_id = await r.create(pipeline_id, revision_id=conf.get("revision_id"))
        fields = {k: conf[k] for k in ("eval_set_id", "sweep_id") if k in conf}
        await r.update(run_id, params=conf.get("context"), **fields)
        return run_id

    monkeypatch.setattr(trig, "trigger_dag_run", _trigger)


@pytest.fixture
def sample_json_file(tmp_path):
    data = [
        {"name": "alice", "age": 30, "score": 9.5, "active": True},
        {"name": "bob", "age": 25, "score": 8.0, "active": False},
        {"name": "carol", "age": 35, "score": 7.5, "active": True},
    ]
    p = tmp_path / "sample.json"
    p.write_text(json.dumps(data))
    return str(p)
