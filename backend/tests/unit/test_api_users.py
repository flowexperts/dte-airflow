"""User / role management API tests."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.user import UserBase
from dte.security.passwords import hash_password


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed(fake_stores, uid: str, email: str, pw: str = "pw"):
    _run(fake_stores["user"].save(UserBase(id=uid, email=email), password_hash=hash_password(pw)))


# ── first-user auto-admin ────────────────────────────────────────────────────

def test_first_register_becomes_admin(monkeypatch, fake_stores):
    monkeypatch.setenv("DTE_ALLOW_REGISTRATION", "true")
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": "first@x.com", "password": "pw"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["roles"] == ["admin"]
    assert "pipeline:read" in body["permissions"]


def test_second_register_has_no_roles(monkeypatch, fake_stores):
    monkeypatch.setenv("DTE_ALLOW_REGISTRATION", "true")
    _seed(fake_stores, "existing", "already@x.com")
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": "second@x.com", "password": "pw"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["roles"] == []
    assert body["permissions"] == []


# ── /auth/me includes roles + permissions ────────────────────────────────────

def test_me_returns_roles_and_permissions(fake_stores):
    # The autouse fake user is admin.
    c = TestClient(app)
    r = c.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert "roles" in body and "permissions" in body
    assert "pipeline:read" in body["permissions"]


# ── /api/users list + get + create + delete ──────────────────────────────────

def test_list_users_returns_seeded(fake_stores):
    _seed(fake_stores, "u1", "u1@x.com")
    _seed(fake_stores, "u2", "u2@x.com")
    r = TestClient(app).get("/api/users")
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()}
    assert {"u1@x.com", "u2@x.com"} <= emails


def test_create_user_endpoint(fake_stores):
    r = TestClient(app).post("/api/users", json={"email": "new@x.com", "password": "pw"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "new@x.com"


def test_create_user_conflict(fake_stores):
    _seed(fake_stores, "u3", "dup@x.com")
    r = TestClient(app).post("/api/users", json={"email": "dup@x.com", "password": "pw"})
    assert r.status_code == 409


def test_delete_user(fake_stores):
    _seed(fake_stores, "gone", "gone@x.com")
    r = TestClient(app).delete("/api/users/gone")
    assert r.status_code == 204
    assert TestClient(app).get("/api/users/gone").status_code == 404


# ── role assignment ──────────────────────────────────────────────────────────

def test_assign_role_grants_permissions(fake_stores):
    _seed(fake_stores, "u4", "u4@x.com")
    r = TestClient(app).post("/api/users/u4/roles", json={"role_id": "viewer"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "viewer" in body["roles"]
    assert "pipeline:read" in body["permissions"]
    assert "pipeline:write" not in body["permissions"]


def test_assign_unknown_role_422(fake_stores):
    _seed(fake_stores, "u5", "u5@x.com")
    r = TestClient(app).post("/api/users/u5/roles", json={"role_id": "nope"})
    assert r.status_code == 422


def test_assign_role_to_unknown_user_404(fake_stores):
    r = TestClient(app).post("/api/users/ghost/roles", json={"role_id": "viewer"})
    assert r.status_code == 404


def test_revoke_role(fake_stores):
    _seed(fake_stores, "u6", "u6@x.com")
    TestClient(app).post("/api/users/u6/roles", json={"role_id": "editor"})
    r = TestClient(app).delete("/api/users/u6/roles/editor")
    assert r.status_code == 204
    body = TestClient(app).get("/api/users/u6").json()
    assert "editor" not in body["roles"]


def test_revoke_missing_role_404(fake_stores):
    _seed(fake_stores, "u7", "u7@x.com")
    r = TestClient(app).delete("/api/users/u7/roles/viewer")
    assert r.status_code == 404


def test_list_roles_returns_seeded(fake_stores):
    r = TestClient(app).get("/api/roles")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert {"admin", "editor", "viewer"} <= ids
