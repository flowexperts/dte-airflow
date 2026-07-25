"""Assert HTTP RED metrics land in /metrics after hitting real routes."""
from __future__ import annotations

from fastapi.testclient import TestClient

from dte.api.main import app


def test_http_requests_total_increments_after_request():
    c = TestClient(app)
    # Trigger any known route — /healthz is always available and unauthenticated.
    c.get("/healthz")
    body = c.get("/metrics/", follow_redirects=True).text

    # Counter must appear with the /healthz route template.
    assert "http_requests_total" in body
    assert 'route="/healthz"' in body


def test_http_request_duration_seconds_registered():
    c = TestClient(app)
    c.get("/healthz")
    body = c.get("/metrics/", follow_redirects=True).text
    assert "http_request_duration_seconds_bucket" in body
    assert 'route="/healthz"' in body


def test_metrics_endpoint_itself_is_not_counted():
    """/metrics scrapes shouldn't inflate their own counter."""
    c = TestClient(app)
    body_a = c.get("/metrics/", follow_redirects=True).text
    c.get("/metrics/", follow_redirects=True)
    body_b = c.get("/metrics/", follow_redirects=True).text
    # Neither request added a metrics-endpoint counter line.
    assert 'route="/metrics"' not in body_a
    assert 'route="/metrics"' not in body_b
