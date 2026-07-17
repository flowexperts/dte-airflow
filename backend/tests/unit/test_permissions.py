"""Permission enum + requires() dep + user_has_perm() tests."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from dte.api.deps import get_current_user
from dte.models.user import Role, User
from dte.security.permissions import (
    ALL_PERMISSIONS,
    ADMIN_PERMISSIONS,
    EDITOR_PERMISSIONS,
    VIEWER_PERMISSIONS,
    requires,
    user_has_perm,
)


def _user_with(perms: list[str]) -> User:
    u = User(id="u", email="u@x.com", is_active=True, password_hash="x")
    u.narrow_roles([Role(id="r", name="r", permissions=perms)])
    return u


# ── enum / canned role sets ──────────────────────────────────────────────────

def test_admin_has_every_permission():
    assert set(ADMIN_PERMISSIONS) == set(ALL_PERMISSIONS)


def test_editor_has_reads_and_writes_and_action_perms():
    assert "pipeline:read" in EDITOR_PERMISSIONS
    assert "pipeline:write" in EDITOR_PERMISSIONS
    assert "pipeline:trigger" in EDITOR_PERMISSIONS
    assert "connection:test" in EDITOR_PERMISSIONS
    assert "pipeline:delete" not in EDITOR_PERMISSIONS
    assert "user:delete" not in EDITOR_PERMISSIONS


def test_viewer_is_read_only():
    for p in VIEWER_PERMISSIONS:
        assert p.endswith(":read")
    assert "pipeline:write" not in VIEWER_PERMISSIONS
    assert "pipeline:trigger" not in VIEWER_PERMISSIONS


# ── user_has_perm ────────────────────────────────────────────────────────────

def test_user_has_perm_positive():
    u = _user_with(["pipeline:read"])
    assert user_has_perm(u, "pipeline:read") is True


def test_user_has_perm_negative():
    u = _user_with(["pipeline:read"])
    assert user_has_perm(u, "pipeline:delete") is False


def test_user_permissions_are_union_of_roles():
    u = User(id="u", email="u@x.com", is_active=True, password_hash="x")
    u.narrow_roles([
        Role(id="a", name="a", permissions=["pipeline:read"]),
        Role(id="b", name="b", permissions=["pipeline:write", "connection:test"]),
    ])
    assert u.permissions == {"pipeline:read", "pipeline:write", "connection:test"}


def test_user_no_roles_has_no_perms():
    u = User(id="u", email="u@x.com", is_active=True, password_hash="x")
    assert u.permissions == set()


# ── requires() dep — real HTTP via a minimal FastAPI ─────────────────────────

def _mini_app(user: User) -> TestClient:
    app = FastAPI()

    @app.get("/gated", dependencies=[Depends(requires("pipeline:read"))])
    async def gated():
        return {"ok": True}

    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_requires_allows_when_perm_present():
    c = _mini_app(_user_with(["pipeline:read"]))
    r = c.get("/gated")
    assert r.status_code == 200


def test_requires_forbids_when_perm_missing():
    c = _mini_app(_user_with(["source:read"]))
    r = c.get("/gated")
    assert r.status_code == 403
    assert "pipeline:read" in r.json()["detail"]


def test_requires_forbids_when_user_has_no_roles():
    u = User(id="u", email="u@x.com", is_active=True, password_hash="x")
    c = _mini_app(u)
    r = c.get("/gated")
    assert r.status_code == 403
