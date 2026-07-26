"""Rate-limiting tests for auth endpoints.

Verifies that the per-IP rate limiter installed by slowapi:
  - allows the first N requests within the window
  - returns 429 on the (N+1)th request within the same window

The global ``_disable_rate_limiter`` autouse fixture in conftest.py disables
the limiter for all tests so serial auth tests don't trip the window.  This
file re-enables it in ``enable_limiter`` (autouse for this module) and resets
the in-memory hit counters before/after each test so cases are isolated.

Limits under test:
  login    → 5/minute  (DTE_AUTH_LOGIN_RATE_LIMIT default)
  register → 3/minute  (DTE_AUTH_REGISTER_RATE_LIMIT default)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dte.api.limiter import limiter
from dte.api.main import app


@pytest.fixture(autouse=True)
def enable_limiter():
    """Enable the limiter for rate-limit tests and reset counters around each."""
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False  # leave disabled so the global fixture restores cleanly


# ── /api/auth/login ──────────────────────────────────────────────────────────

def test_login_rate_limit_blocks_on_sixth_attempt(fake_stores):
    """The 6th login attempt from the same IP within 1 minute should get 429.

    Default login limit is 5/minute; first 5 → 401 (wrong creds), 6th → 429.
    """
    c = TestClient(app, headers={"X-Forwarded-For": "10.0.0.1"})
    payload = {"email": "ghost@x.com", "password": "wrong"}
    statuses = [c.post("/api/auth/login", json=payload).status_code for _ in range(6)]
    # First 5 → 401 (wrong credentials); 6th → 429 (rate limited)
    assert statuses[:5] == [401] * 5, f"Expected 401s, got {statuses[:5]}"
    assert statuses[5] == 429, f"Expected 429 on 6th attempt, got {statuses[5]}"


# NOTE: per-IP isolation is enforced by slowapi.util.get_remote_address on
# request.client.host. FastAPI TestClient always reports the same fake client
# host regardless of X-Forwarded-For (no ProxyHeaders middleware in tests),
# so a per-IP isolation test would need a real ASGI transport. Skipped here;
# the isolation is a slowapi guarantee, not our code path.


# ── /api/auth/register ───────────────────────────────────────────────────────

def test_register_rate_limit_blocks_on_fourth_attempt(monkeypatch, fake_stores):
    """The 4th register attempt from the same IP within 1 minute should get 429.

    Default register limit is 3/minute; first 3 → 201 (created), 4th → 429.
    """
    monkeypatch.setenv("DTE_ALLOW_REGISTRATION", "true")
    c = TestClient(app, headers={"X-Forwarded-For": "10.0.0.4"})
    statuses = []
    for i in range(4):
        payload = {"email": f"user{i}@x.com", "password": "pw"}
        statuses.append(c.post("/api/auth/register", json=payload).status_code)
    # First 3 → 201 (created); 4th → 429
    assert statuses[:3] == [201] * 3, f"Expected 201s, got {statuses[:3]}"
    assert statuses[3] == 429, f"Expected 429 on 4th attempt, got {statuses[3]}"


def test_login_rate_limit_configurable(monkeypatch, fake_stores):
    """Overriding DTE_AUTH_LOGIN_RATE_LIMIT changes the enforced window.

    Set to 2/minute — 2nd request passes, 3rd → 429. Because the limiter
    reads the limit callable on each request, the monkeypatch takes effect
    without restarting the server.
    """
    monkeypatch.setenv("DTE_AUTH_LOGIN_RATE_LIMIT", "2/minute")
    c = TestClient(app, headers={"X-Forwarded-For": "10.0.0.2"})
    payload = {"email": "ghost@x.com", "password": "wrong"}
    statuses = [c.post("/api/auth/login", json=payload).status_code for _ in range(3)]
    assert statuses[:2] == [401, 401], f"Expected two 401s, got {statuses[:2]}"
    assert statuses[2] == 429, f"Expected 429 on 3rd attempt, got {statuses[2]}"


def test_register_rate_limit_configurable(monkeypatch, fake_stores):
    """Overriding DTE_AUTH_REGISTER_RATE_LIMIT changes the enforced window."""
    monkeypatch.setenv("DTE_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("DTE_AUTH_REGISTER_RATE_LIMIT", "2/minute")
    c = TestClient(app, headers={"X-Forwarded-For": "10.0.0.5"})
    statuses = []
    for i in range(3):
        payload = {"email": f"cfg{i}@x.com", "password": "pw"}
        statuses.append(c.post("/api/auth/register", json=payload).status_code)
    assert statuses[:2] == [201, 201], f"Expected two 201s, got {statuses[:2]}"
    assert statuses[2] == 429, f"Expected 429 on 3rd attempt, got {statuses[2]}"
