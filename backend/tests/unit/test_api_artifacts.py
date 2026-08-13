"""`GET /api/artifacts/{key}` — where the document inspector fetches bytes."""

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.artifacts import doc_key, get_artifact_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    yield TestClient(app)
    app.dependency_overrides.clear()


def _store(content: bytes, media_type: str = "application/pdf") -> str:
    key = doc_key(content)
    get_artifact_store().put(key, content, media_type)
    return key


def test_get_artifact_returns_bytes_and_media_type(client):
    key = _store(b"%PDF-1.4 fake", "application/pdf")
    r = client.get(f"/api/artifacts/{key}")
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 fake"
    assert r.headers["content-type"] == "application/pdf"


def test_artifacts_are_cached_forever(client):
    """Content-addressed: the bytes under a key can never change."""
    key = _store(b"stable")
    r = client.get(f"/api/artifacts/{key}")
    assert "immutable" in r.headers["cache-control"]


def test_missing_artifact_is_404(client):
    assert client.get(f"/api/artifacts/{'0' * 64}").status_code == 404


@pytest.mark.parametrize("bad", ["not-hex", "abc", "A" * 64])
def test_malformed_key_is_400_not_404(client, bad):
    """A traversal attempt is a bad request, not a missing resource."""
    assert client.get(f"/api/artifacts/{bad}").status_code == 400


def test_path_traversal_does_not_escape_the_store(client, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("do not serve me")
    # Encoded traversal — FastAPI hands this through as a single path segment.
    r = client.get("/api/artifacts/..%2F..%2Fsecret.txt")
    assert r.status_code in (400, 404)
    assert b"do not serve me" not in r.content


def test_unknown_media_type_falls_back_to_octet_stream(client, tmp_path):
    key = doc_key(b"raw")
    store = get_artifact_store()
    store.put(key, b"raw", "text/plain")
    # Drop the sidecar so media_type() returns None.
    store._meta(key).unlink()
    r = client.get(f"/api/artifacts/{key}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
