"""Smoke test for the /metrics endpoint (P3 #30)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from dte.api.main import app


def test_metrics_endpoint_returns_prometheus_text():
    c = TestClient(app)
    r = c.get("/metrics")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "text/plain" in ct  # Prometheus text exposition format


def test_metrics_endpoint_exposes_domain_metrics():
    """Import-side registration means dte_* metrics show up even at zero."""
    c = TestClient(app)
    body = c.get("/metrics").text
    assert "dte_pipeline_runs_total" in body
    assert "dte_pipeline_run_duration_seconds" in body
    assert "dte_active_runs" in body
