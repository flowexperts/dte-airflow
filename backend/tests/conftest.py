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

from dte.api.limiter import limiter
from dte.api.main import app
from dte.api.deps import (
    get_pipeline_revision_store,
    get_pipeline_store,
    get_run_event_store,
    get_run_store,
    get_source_store,
    get_destination_store,
    get_connection_store,
    get_user_store,
    get_role_store,
    get_current_user,
    get_current_tenant_id,
    get_dashboard_store,
    get_lookup_table_store,
    get_eval_example_store,
    get_eval_set_store,
    get_schedule_store,
)
from dte.models.pipeline import Connection
from dte.models.user import Role, User, UserBase
from dte.security.jwt import create_access_token
from dte.security.passwords import hash_password
from tests.fakes import (
    FakePipelineRevisionStore,
    FakePipelineStore,
    FakeRunEventStore,
    FakeRunStore,
    FakeSourceStore,
    FakeDestinationStore,
    FakeConnectionStore,
    FakeRoleStore,
    FakeUserStore,
    FakeDashboardStore,
    FakeLookupTableStore,
    FakeEvalExampleStore,
    FakeEvalSetStore,
    FakeScheduleStore,
)


def _make_local_fs_connection() -> Connection:
    """Build the pre-seeded local_fs Connection instance."""
    return Connection(
        id="local_fs",
        connection_type="local_fs",
        credentials={},
    )


def _fake_test_user() -> User:
    from dte.models.user import Role
    from dte.security.permissions import ADMIN_PERMISSIONS
    u = User(
        id="test-user",
        email="test@example.com",
        is_active=True,
        password_hash="unused-in-tests",
    )
    # Attach an admin role so autouse tests pass every requires(...) gate.
    # RBAC-specific tests override get_current_user with a scoped user.
    u.narrow_roles([Role(id="admin", name="admin", permissions=list(ADMIN_PERMISSIONS))])
    # Embed the default tenant so multi-tenant deps work in tests.
    object.__setattr__(u, "_tenant_id", "default")
    return u


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
def _disable_rate_limiter():
    """Disable the global slowapi limiter for every test.

    Unit tests that call login/register multiple times in sequence would
    otherwise trip the per-IP window. ``test_rate_limit.py`` re-enables the
    limiter explicitly inside its own fixture so the 429 path is testable.
    """
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture(autouse=True)
def fake_stores():
    from dte.security.permissions import (
        ADMIN_PERMISSIONS,
        EDITOR_PERMISSIONS,
        VIEWER_PERMISSIONS,
    )
    role_store = FakeRoleStore()
    # Seed the three canned roles (mirrors alembic 011).
    role_store._data["admin"] = Role(id="admin", name="admin", permissions=list(ADMIN_PERMISSIONS))
    role_store._data["editor"] = Role(id="editor", name="editor", permissions=list(EDITOR_PERMISSIONS))
    role_store._data["viewer"] = Role(id="viewer", name="viewer", permissions=list(VIEWER_PERMISSIONS))

    p, r, re, s, d, c, u, lt, pr, sch = (
        FakePipelineStore(),
        FakeRunStore(),
        FakeRunEventStore(),
        FakeSourceStore(),
        FakeDestinationStore(),
        FakeConnectionStore(),
        FakeUserStore(role_store=role_store),
        FakeLookupTableStore(),
        FakePipelineRevisionStore(),
        FakeScheduleStore(),
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
    app.dependency_overrides[get_user_store] = lambda: u
    app.dependency_overrides[get_role_store] = lambda: role_store
    app.dependency_overrides[get_lookup_table_store] = lambda: lt
    app.dependency_overrides[get_dashboard_store] = lambda: dash
    app.dependency_overrides[get_pipeline_revision_store] = lambda: pr
    app.dependency_overrides[get_schedule_store] = lambda: sch
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
        "user": u,
        "role": role_store,
        "lookup_table": lt,
        "dashboard": dash,
        "pipeline_revision": pr,
        "schedule": sch,
        "eval_set": es,
        "eval_example": ee,
    }
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(fake_stores):
    """Return an Authorization header for a freshly-created user.

    Use with `TestClient(app).get(..., headers=auth_headers)` when you
    need a real JWT (e.g. testing the round-trip). Synchronous to avoid
    perturbing the event loop that sibling test files reuse."""
    import asyncio
    users: FakeUserStore = fake_stores["user"]
    user = UserBase(id="auth-fixture-user", email="fixture@example.com")
    asyncio.get_event_loop().run_until_complete(
        users.save(user, password_hash=hash_password("fixturepass"))
    )
    token = create_access_token(user_id=user.id, email=str(user.email))
    return {"Authorization": f"Bearer {token}"}


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
