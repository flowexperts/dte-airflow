"""RBAC matrix — spot-check each role against a representative set of
routes. The `test_route_permissions.py` introspection test covers the
"every route is gated" property; this test verifies the gates make
policy sense (viewer can't write, editor can't delete, etc.)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from dte.api.deps import get_current_user
from dte.api.main import app
from dte.models.user import User
from dte.security.permissions import (
    ADMIN_PERMISSIONS,
    EDITOR_PERMISSIONS,
    VIEWER_PERMISSIONS,
)


def _override_user(perms: list[str]) -> User:
    u = User(id="u", email="u@x.com", permissions=perms)
    app.dependency_overrides[get_current_user] = lambda: u
    return u


# ── viewer ────────────────────────────────────────────────────────────────────

def test_viewer_can_list_pipelines():
    _override_user(VIEWER_PERMISSIONS)
    assert TestClient(app).get("/api/pipelines").status_code == 200


def test_viewer_cannot_create_pipeline():
    _override_user(VIEWER_PERMISSIONS)
    r = TestClient(app).post("/api/pipelines", json={
        "id": "p1", "name": "p", "sources": [], "steps": [], "output_id": "d"
    })
    assert r.status_code == 403
    assert "pipeline:write" in r.json()["detail"]


def test_viewer_cannot_delete_pipeline():
    _override_user(VIEWER_PERMISSIONS)
    assert TestClient(app).delete("/api/pipelines/anything").status_code == 403


def test_viewer_cannot_trigger_pipeline():
    _override_user(VIEWER_PERMISSIONS)
    assert TestClient(app).post("/api/pipelines/anything/trigger").status_code == 403


def test_viewer_cannot_test_connection():
    _override_user(VIEWER_PERMISSIONS)
    assert TestClient(app).post("/api/connections/anything/test").status_code == 403


# ── editor ────────────────────────────────────────────────────────────────────

def test_editor_can_read_pipelines():
    _override_user(EDITOR_PERMISSIONS)
    assert TestClient(app).get("/api/pipelines").status_code == 200


def test_editor_can_trigger_pipeline():
    """Auth passes; the actual pipeline may 404 — we only care about the gate."""
    _override_user(EDITOR_PERMISSIONS)
    r = TestClient(app).post("/api/pipelines/nope/trigger")
    assert r.status_code != 403


def test_editor_can_test_connection():
    _override_user(EDITOR_PERMISSIONS)
    r = TestClient(app).post("/api/connections/nope/test")
    assert r.status_code != 403


def test_editor_cannot_delete_pipeline():
    _override_user(EDITOR_PERMISSIONS)
    assert TestClient(app).delete("/api/pipelines/anything").status_code == 403


def test_admin_can_delete_pipeline():
    """Passes the gate — endpoint may 404, that's fine."""
    _override_user(ADMIN_PERMISSIONS)
    r = TestClient(app).delete("/api/pipelines/anything")
    assert r.status_code != 403


def test_user_with_no_roles_gets_403_on_everything():
    _override_user([])
    for path in ("/api/pipelines", "/api/sources", "/api/destinations", "/api/connections"):
        assert TestClient(app).get(path).status_code == 403, path
