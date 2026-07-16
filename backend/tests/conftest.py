"""Pytest fixtures.

Autouse `fake_stores` attaches in-memory `Fake*Store` implementations to
the FastAPI app for every test. Individual tests that need to inspect or
seed a store still install their own override in a fixture — the autouse
just guarantees no test ever hits the real Postgres deps.
"""
import json
import pytest

from dte.api.main import app
from dte.api.deps import (
    get_pipeline_store,
    get_run_store,
    get_source_store,
    get_destination_store,
    get_connection_store,
)
from dte.models.pipeline import Connection
from tests.fakes import (
    FakePipelineStore,
    FakeRunStore,
    FakeSourceStore,
    FakeDestinationStore,
    FakeConnectionStore,
)


def _make_local_fs_connection() -> Connection:
    """Build the pre-seeded local_fs Connection instance."""
    row = Connection(
        id="local_fs",
        connection_type="local_fs",
        credentials_encrypted=b"",
    )
    object.__setattr__(row, "credentials", {})
    return row


@pytest.fixture(autouse=True)
def fake_stores():
    p, r, s, d, c = (
        FakePipelineStore(),
        FakeRunStore(),
        FakeSourceStore(),
        FakeDestinationStore(),
        FakeConnectionStore(),
    )
    # Every test gets a `local_fs` connection pre-seeded — most sources /
    # destinations use it, tests don't have to re-declare it every time.
    c._data["local_fs"] = _make_local_fs_connection()
    app.dependency_overrides[get_pipeline_store] = lambda: p
    app.dependency_overrides[get_run_store] = lambda: r
    app.dependency_overrides[get_source_store] = lambda: s
    app.dependency_overrides[get_destination_store] = lambda: d
    app.dependency_overrides[get_connection_store] = lambda: c
    yield {"pipeline": p, "run": r, "source": s, "destination": d, "connection": c}
    app.dependency_overrides.clear()


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
