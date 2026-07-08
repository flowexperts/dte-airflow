import importlib

from fastapi.testclient import TestClient


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
