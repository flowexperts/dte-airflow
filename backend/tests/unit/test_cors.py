from fastapi.testclient import TestClient
from dte.api.main import app


def test_cors_preflight_allows_localhost_3000():
    client = TestClient(app)
    r = client.options(
        "/api/pipelines",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "GET" in r.headers.get("access-control-allow-methods", "")


def test_cors_actual_request_includes_allow_origin():
    client = TestClient(app)
    r = client.get("/api/pipelines", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_unknown_origin():
    client = TestClient(app)
    r = client.get("/api/pipelines", headers={"Origin": "https://evil.example.com"})
    # request succeeds but no CORS header is emitted for disallowed origin
    assert r.headers.get("access-control-allow-origin") in (None, "")
