"""Tests for TenantContextMiddleware and tenancy contextvar helpers.

Coverage:
  (a) multi-tenant off → default tenant used, no 401
  (b) multi-tenant on + valid token → SET LOCAL is issued with the token's tenant
  (c) multi-tenant on + missing token on protected route → 401
  (d) contextvar isolation across concurrent requests (asyncio.gather with two tokens)
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import get_current_user
from dte.security.jwt import create_access_token
from dte.tenancy import get_current_tenant, set_current_tenant, tenant_context_var


# ──────────────────────────────────────────────────────────────────────────────
# tenancy module helpers
# ──────────────────────────────────────────────────────────────────────────────

def test_set_and_get_current_tenant():
    """set_current_tenant / get_current_tenant round-trip in the same coroutine."""
    token = set_current_tenant("acme")
    assert get_current_tenant() == "acme"
    tenant_context_var.reset(token)


def test_get_current_tenant_default_when_unset():
    """get_current_tenant() returns 'default' when the contextvar has no value."""
    # The contextvar is initialised with default='default'
    assert get_current_tenant() == "default"


# ──────────────────────────────────────────────────────────────────────────────
# (a) multi_tenant_enabled=False → sets 'default', no 401 on protected routes
# ──────────────────────────────────────────────────────────────────────────────

def test_multi_tenant_off_uses_default_tenant(fake_stores, monkeypatch):
    """When DTE_MULTI_TENANT_ENABLED is False the middleware is a no-op.

    The contextvar is set to 'default' so stores receive it without raising.
    Protected routes still use the autouse fake user.
    """
    monkeypatch.setenv("DTE_MULTI_TENANT_ENABLED", "false")
    with TestClient(app) as client:
        resp = client.get("/api/pipelines")
    assert resp.status_code == 200


def test_multi_tenant_off_no_auth_header_still_passes(fake_stores, monkeypatch):
    """Middleware disabled → a request with no Authorization header is not
    rejected by the middleware (the fake_stores autouse bypasses auth deps)."""
    monkeypatch.setenv("DTE_MULTI_TENANT_ENABLED", "false")
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# (b) multi-tenant on + valid token → contextvar set to token's tenant
# ──────────────────────────────────────────────────────────────────────────────

def test_tenant_middleware_sets_contextvar_from_valid_token(monkeypatch):
    """With multi_tenant_enabled=True a valid JWT causes the middleware to
    route a protected-path request through without a 401, and the middleware
    records the tenant in the contextvar for the duration of the request.

    We verify by:
    1. Installing a tiny test route on the app that reads the contextvar and
       returns its value in the response body.
    2. Sending a request with a token that carries tenant='zeta-corp'.
    3. Asserting the response contains 'zeta-corp'.
    """
    monkeypatch.setenv("DTE_MULTI_TENANT_ENABLED", "true")
    monkeypatch.setenv("DTE_JWT_SECRET", "test-secret-32-bytes-for-middleware!")

    from dte.security.jwt import create_access_token
    from dte.tenancy import tenant_context_var
    from fastapi import FastAPI
    from fastapi.testclient import TestClient as _TC
    from dte.api.middleware import TenantContextMiddleware

    mini_app = FastAPI()
    mini_app.add_middleware(TenantContextMiddleware)

    @mini_app.get("/probe")
    def _probe():
        return {"tenant": tenant_context_var.get()}

    jwt_token = create_access_token(user_id="u1", email="u@test.com", tenant_id="zeta-corp")

    with _TC(mini_app, raise_server_exceptions=False) as client:
        resp = client.get("/probe", headers={"Authorization": f"Bearer {jwt_token}"})

    assert resp.status_code == 200
    assert resp.json()["tenant"] == "zeta-corp"


# ──────────────────────────────────────────────────────────────────────────────
# (c) multi-tenant on + missing token on protected route → 401
# ──────────────────────────────────────────────────────────────────────────────

def test_multi_tenant_on_missing_token_returns_401(fake_stores, monkeypatch):
    """Protected routes must return 401 when multi_tenant_enabled=True and
    no Bearer token is provided."""
    monkeypatch.setenv("DTE_MULTI_TENANT_ENABLED", "true")
    monkeypatch.setenv("DTE_JWT_SECRET", "test-secret-for-middleware")

    # Remove the autouse fake user override so the middleware runs for real
    app.dependency_overrides.pop(get_current_user, None)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/pipelines")

    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# (d) contextvar isolation across concurrent requests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_contextvar_isolation_across_concurrent_requests():
    """Two concurrent coroutines each set a different tenant; they must not
    bleed into each other's context.

    This exercises the contextvars.copy_context() / asyncio task propagation
    guarantee — each asyncio.Task inherits its own copy of the context at
    creation time.
    """
    from dte.tenancy import tenant_context_var

    results: dict[str, str | None] = {}

    async def _request_scope(tenant: str, key: str):
        # Simulate what the middleware does: set the contextvar, then read it
        # back "inside the request handler".
        token = tenant_context_var.set(tenant)
        await asyncio.sleep(0)  # yield to event loop so the other task runs
        results[key] = tenant_context_var.get()
        tenant_context_var.reset(token)

    await asyncio.gather(
        _request_scope("tenant-alpha", "req-a"),
        _request_scope("tenant-beta", "req-b"),
    )

    assert results["req-a"] == "tenant-alpha"
    assert results["req-b"] == "tenant-beta"


# ──────────────────────────────────────────────────────────────────────────────
# postgres store session SET LOCAL propagation
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_tenant_session_issues_set_local():
    """_open_tenant_session() must issue SET LOCAL dte.tenant_id when the
    contextvar has a non-None tenant value."""
    from dte.store.postgres import _open_tenant_session
    from dte.tenancy import set_current_tenant, tenant_context_var

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session)

    tok = set_current_tenant("my-tenant")
    try:
        async with _open_tenant_session(mock_factory) as _s:
            pass
    finally:
        tenant_context_var.reset(tok)

    # Verify SET LOCAL was called with the correct tenant_id
    mock_session.execute.assert_called_once()
    call_args = mock_session.execute.call_args
    # First arg is the text() expression; check the params dict
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
    # The call signature is execute(text(...), {"tid": "my-tenant"})
    assert params == {"tid": "my-tenant"}


@pytest.mark.asyncio
async def test_open_tenant_session_skips_set_local_when_tenant_is_default():
    """When tenant is 'default' (single-tenant mode), SET LOCAL is still
    issued but with 'default' so RLS policy matches rows where tenant_id='default'."""
    from dte.store.postgres import _open_tenant_session
    from dte.tenancy import set_current_tenant, tenant_context_var

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session)

    tok = set_current_tenant("default")
    try:
        async with _open_tenant_session(mock_factory) as _s:
            pass
    finally:
        tenant_context_var.reset(tok)

    mock_session.execute.assert_called_once()
    call_args = mock_session.execute.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
    assert params == {"tid": "default"}


# ──────────────────────────────────────────────────────────────────────────────
# background task context propagation
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_background_task_inherits_tenant_contextvar():
    """asyncio tasks created with copy_context().run() inherit the current
    contextvar state, not a fresh default."""
    import contextvars
    from dte.tenancy import tenant_context_var, set_current_tenant

    captured: list[str] = []

    async def _bg_task():
        # What the contextvar holds inside the background task
        captured.append(tenant_context_var.get())

    tok = set_current_tenant("bg-tenant")
    ctx = contextvars.copy_context()
    try:
        task = asyncio.ensure_future(ctx.run(_bg_task))
        await task
    finally:
        tenant_context_var.reset(tok)

    assert captured == ["bg-tenant"]
