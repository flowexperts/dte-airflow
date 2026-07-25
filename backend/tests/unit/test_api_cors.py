import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _restore_main_module():
    """test_api_cors.py reloads dte.api.main to pick up a new
    DTE_CORS_ORIGINS. That reload swaps `app` for a fresh FastAPI()
    instance, but conftest.py holds a module-level reference to the
    ORIGINAL app and installs its autouse dep overrides on it. If we
    leave the reloaded module active, every downstream test attaches
    overrides to a dead app. Save the original `app` and restore it
    on the module after each test in this file."""
    import dte.api.main as main_module
    original_app = main_module.app
    yield
    main_module.app = original_app


def _build_client(monkeypatch, origins: str | None):
    if origins is None:
        monkeypatch.delenv("DTE_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("DTE_CORS_ORIGINS", origins)
    import dte.api.main as main_module
    importlib.reload(main_module)
    return TestClient(main_module.app)


def test_cors_preflight_allows_localhost_3000(monkeypatch):
    client = _build_client(monkeypatch, None)
    resp = client.options(
        "/api/pipelines",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_allows_vite_5173(monkeypatch):
    client = _build_client(monkeypatch, None)
    resp = client.options(
        "/api/pipelines",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_custom_origin_from_env(monkeypatch):
    client = _build_client(monkeypatch, "https://app.example.com")
    resp = client.options(
        "/api/pipelines",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://app.example.com"


def test_cors_disallowed_origin_has_no_header(monkeypatch):
    client = _build_client(monkeypatch, "https://app.example.com")
    resp = client.options(
        "/api/pipelines",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in resp.headers
