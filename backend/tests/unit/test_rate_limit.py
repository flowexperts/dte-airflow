"""Rate-limiting tests for auth endpoints.

Verifies that the per-IP rate limiter installed by slowapi:
  - allows the first N requests within the window
  - returns 429 on the (N+1)th request within the same window

slowapi's in-memory storage is reset between tests via the limiter fixture.
The TestClient sets headers for each request so slowapi's `get_remote_address`
sees a consistent fake client IP.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dte.api.limiter import limiter
from dte.api.main import app


@pytest.fixture(autouse=True)
def reset_limiter():
    """Clear slowapi's in-memory hit counters before every test."""
    limiter.reset()
    yield
    limiter.reset()


# ── /api/auth/login ──────────────────────────────────────────────────────────

def test_login_rate_limit_blocks_on_sixth_attempt(fake_stores):
    """The 6th login attempt from the same IP within 1 minute should get 429."""
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

def test_register_rate_limit_blocks_on_sixth_attempt(monkeypatch, fake_stores):
    """The 6th register attempt from the same IP within 1 minute should get 429."""
    monkeypatch.setenv("DTE_ALLOW_REGISTRATION", "true")
    c = TestClient(app, headers={"X-Forwarded-For": "10.0.0.4"})
    statuses = []
    for i in range(6):
        payload = {"email": f"user{i}@x.com", "password": "pw"}
        statuses.append(c.post("/api/auth/register", json=payload).status_code)
    # First 5 → 201 (created); 6th → 429
    assert statuses[:5] == [201] * 5, f"Expected 201s, got {statuses[:5]}"
    assert statuses[5] == 429, f"Expected 429 on 6th attempt, got {statuses[5]}"
