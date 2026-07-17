"""Auth route tests — register, login, /me, and router-level guards.

Tests are synchronous (not `async def`) so we don't perturb the event
loop state that `_run(...) = asyncio.get_event_loop().run_until_complete`
in sibling test files relies on. Async work (seeding fake stores) happens
via the `_run` helper below.
"""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import get_current_user
from dte.models.user import UserBase
from dte.security.jwt import create_access_token
from dte.security.passwords import hash_password


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _bypass_off():
    """Remove the autouse `get_current_user` override so the real
    dependency runs (which reads the Authorization header)."""
    app.dependency_overrides.pop(get_current_user, None)


def _seed_user(fake_stores, email="me@x.com", password="pw", is_active=True):
    users = fake_stores["user"]
    user = UserBase(id="uid-" + email, email=email, is_active=is_active)
    _run(users.save(user, password_hash=hash_password(password)))
    return user


# ── /auth/register ────────────────────────────────────────────────────────────

def test_register_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DTE_ALLOW_REGISTRATION", raising=False)
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": "a@x.com", "password": "pw"})
    assert r.status_code == 403


def test_register_creates_user(monkeypatch, fake_stores):
    monkeypatch.setenv("DTE_ALLOW_REGISTRATION", "true")
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": "a@x.com", "password": "pw"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "a@x.com"
    assert body["is_active"] is True
    assert "id" in body


def test_register_duplicate_email_conflicts(monkeypatch):
    monkeypatch.setenv("DTE_ALLOW_REGISTRATION", "true")
    c = TestClient(app)
    c.post("/api/auth/register", json={"email": "dup@x.com", "password": "pw"})
    r = c.post("/api/auth/register", json={"email": "dup@x.com", "password": "pw2"})
    assert r.status_code == 409


def test_register_invalid_email(monkeypatch):
    monkeypatch.setenv("DTE_ALLOW_REGISTRATION", "true")
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": "not-email", "password": "pw"})
    assert r.status_code == 422


# ── /auth/login ───────────────────────────────────────────────────────────────

def test_login_success(fake_stores):
    _seed_user(fake_stores, "login@x.com", "secret")
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "login@x.com", "password": "secret"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password(fake_stores):
    _seed_user(fake_stores, "wrong@x.com", "secret")
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "wrong@x.com", "password": "nope"})
    assert r.status_code == 401


def test_login_unknown_email(fake_stores):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "ghost@x.com", "password": "pw"})
    assert r.status_code == 401


def test_login_inactive_user_forbidden(fake_stores):
    _seed_user(fake_stores, "dis@x.com", "pw", is_active=False)
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "dis@x.com", "password": "pw"})
    assert r.status_code == 403


# ── /auth/me ──────────────────────────────────────────────────────────────────

def test_me_returns_current_user(fake_stores):
    _seed_user(fake_stores, "me@x.com", "pw")
    token = create_access_token(user_id="uid-me@x.com", email="me@x.com")
    _bypass_off()
    c = TestClient(app)
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "me@x.com"


def test_me_missing_token_401():
    _bypass_off()
    c = TestClient(app)
    r = c.get("/api/auth/me")
    assert r.status_code == 401


def test_me_bad_token_401():
    _bypass_off()
    c = TestClient(app)
    r = c.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


# ── Router-level guards ──────────────────────────────────────────────────────

def test_pipelines_route_requires_auth():
    _bypass_off()
    c = TestClient(app)
    r = c.get("/api/pipelines")
    assert r.status_code == 401


def test_sources_route_requires_auth():
    _bypass_off()
    c = TestClient(app)
    r = c.get("/api/sources")
    assert r.status_code == 401


def test_connections_route_requires_auth():
    _bypass_off()
    c = TestClient(app)
    r = c.get("/api/connections")
    assert r.status_code == 401


def test_pipelines_route_accepts_valid_token(fake_stores):
    _seed_user(fake_stores, "list@x.com", "pw")
    token = create_access_token(user_id="uid-list@x.com", email="list@x.com")
    _bypass_off()
    c = TestClient(app)
    r = c.get("/api/pipelines", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


# ── JWT edge cases ───────────────────────────────────────────────────────────

def test_token_for_deleted_user_401(fake_stores):
    """Token issued for a user id that no longer exists → 401."""
    token = create_access_token(user_id="never-existed", email="x@x.com")
    _bypass_off()
    c = TestClient(app)
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_token_for_disabled_user_401(fake_stores):
    _seed_user(fake_stores, "off@x.com", "pw", is_active=False)
    token = create_access_token(user_id="uid-off@x.com", email="off@x.com")
    _bypass_off()
    c = TestClient(app)
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
