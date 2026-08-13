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


# ── range requests ──────────────────────────────────────────────────────────
#
# A 500-page PDF is tens of megabytes. pdf.js will fetch only the byte ranges
# it needs for the page being viewed — but only if the server advertises that
# it can serve them. Without this the client downloads the whole document to
# render page 1, and the server reads the whole thing into memory to send it.


def test_advertises_range_support(client):
    key = _store(b"0123456789")
    r = client.get(f"/api/artifacts/{key}")
    assert r.headers["accept-ranges"] == "bytes"


def test_range_request_returns_only_that_slice(client):
    key = _store(b"0123456789")
    r = client.get(f"/api/artifacts/{key}", headers={"Range": "bytes=2-5"})
    assert r.status_code == 206
    assert r.content == b"2345"
    assert r.headers["content-range"] == "bytes 2-5/10"
    assert r.headers["content-length"] == "4"


def test_open_ended_range_runs_to_the_end(client):
    key = _store(b"0123456789")
    r = client.get(f"/api/artifacts/{key}", headers={"Range": "bytes=7-"})
    assert r.status_code == 206
    assert r.content == b"789"
    assert r.headers["content-range"] == "bytes 7-9/10"


def test_suffix_range_returns_the_last_n_bytes(client):
    """pdf.js opens a PDF by reading the trailer from the *end* of the file,
    so the suffix form is the first request it makes."""
    key = _store(b"0123456789")
    r = client.get(f"/api/artifacts/{key}", headers={"Range": "bytes=-3"})
    assert r.status_code == 206
    assert r.content == b"789"
    assert r.headers["content-range"] == "bytes 7-9/10"


def test_range_past_the_end_is_clamped_not_an_error(client):
    key = _store(b"0123456789")
    r = client.get(f"/api/artifacts/{key}", headers={"Range": "bytes=5-999"})
    assert r.status_code == 206
    assert r.content == b"56789"


def test_unsatisfiable_range_is_416_with_the_real_size(client):
    key = _store(b"0123456789")
    r = client.get(f"/api/artifacts/{key}", headers={"Range": "bytes=50-60"})
    assert r.status_code == 416
    assert r.headers["content-range"] == "bytes */10"


def test_unparseable_range_falls_back_to_the_whole_body(client):
    """An unrecognised Range is not a client error — RFC 7233 says ignore it.
    Returning 416 here would break any proxy that rewrites the header."""
    key = _store(b"0123456789")
    r = client.get(f"/api/artifacts/{key}", headers={"Range": "pages=1-2"})
    assert r.status_code == 200
    assert r.content == b"0123456789"


def test_range_headers_are_readable_cross_origin():
    """pdf.js runs on :3000 and the API is on :8001, so every range response
    is cross-origin. The browser hides `Content-Range` from JS unless it is
    named here — and pdf.js reads it to learn the document length. Without
    this the viewer silently falls back to downloading whole documents, which
    still *works*, so it would never show up as a failure."""
    from dte.api.main import app as fresh_app

    cors = [m for m in fresh_app.user_middleware if "CORS" in str(m)]
    assert cors, "CORS middleware not installed"
    exposed = cors[0].kwargs.get("expose_headers") or []
    assert {"Content-Range", "Accept-Ranges", "Content-Length"} <= set(exposed)


def test_a_large_artifact_is_not_read_whole_to_serve_one_range(client, monkeypatch):
    """The server-side half of the same problem: `store.get()` pulls the entire
    document into memory. One user opening a 500-page PDF should not cost
    50MB of RSS per request, and ten concurrent users should not cost 500MB.
    """
    key = _store(b"x" * 5_000_000)
    store = get_artifact_store()
    monkeypatch.setattr(
        type(store), "get",
        lambda *a, **k: pytest.fail("whole-artifact read on a ranged request"),
    )
    r = client.get(f"/api/artifacts/{key}", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206
    assert r.content == b"x" * 10


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
