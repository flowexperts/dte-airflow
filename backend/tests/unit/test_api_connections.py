from fastapi.testclient import TestClient
from dte.api.main import app
from dte.models.pipeline import Source


def _conn(cid="c1", ctype="s3"):
    return {
        "id": cid,
        "connection_type": ctype,
        "credentials": {"aws_access_key_id": "AKIA", "aws_secret_access_key": "s3cret"},
    }


def test_create_connection_201_masks_credentials():
    c = TestClient(app)
    r = c.post("/api/connections", json=_conn())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "c1"
    # All present cred fields are masked (dlt's AwsCredentials fills in a
    # default for aws_sts_token_expiration_hours — mask that too).
    assert all(v == "***" for v in body["credentials"].values())
    assert {"aws_access_key_id", "aws_secret_access_key"}.issubset(body["credentials"])


def test_create_duplicate_409(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn())
    r = c.post("/api/connections", json=_conn())
    assert r.status_code == 409


def test_get_default_masks_credentials(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn())
    r = c.get("/api/connections/c1")
    assert r.status_code == 200
    assert r.json()["credentials"]["aws_secret_access_key"] == "***"


def test_get_reveal_returns_plaintext(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn())
    r = c.get("/api/connections/c1?reveal=true")
    assert r.status_code == 200
    assert r.json()["credentials"]["aws_secret_access_key"] == "s3cret"


def test_list_returns_masked_only(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn("c1"))
    c.post("/api/connections", json=_conn("c2"))
    r = c.get("/api/connections")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    # `local_fs` is pre-seeded by the autouse fixture.
    assert {"c1", "c2"}.issubset(ids)
    for row in r.json():
        assert all(v == "***" for v in row["credentials"].values())


def test_update_replaces_credentials(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn())
    updated = _conn()
    updated["credentials"]["aws_secret_access_key"] = "rotated"
    r = c.put("/api/connections/c1", json=updated)
    assert r.status_code == 200
    reveal = c.get("/api/connections/c1?reveal=true").json()
    assert reveal["credentials"]["aws_secret_access_key"] == "rotated"


def test_update_with_empty_credentials_keeps_existing(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn())
    r = c.put("/api/connections/c1", json={"id": "c1", "connection_type": "s3", "credentials": {}})
    assert r.status_code == 200
    reveal = c.get("/api/connections/c1?reveal=true").json()
    assert reveal["credentials"]["aws_secret_access_key"] == "s3cret"


def test_update_id_mismatch_400(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn())
    r = c.put("/api/connections/c1", json=_conn("other"))
    assert r.status_code == 400


def test_delete_unreferenced_204(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn())
    r = c.delete("/api/connections/c1")
    assert r.status_code == 204


def test_delete_referenced_by_source_returns_409(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn())
    # Seed a fake source referencing this connection directly on the
    # store's private dict — avoids spinning up an event loop for a sync test.
    fake_stores["source"]._data["s1"] = Source(
        id="s1", connection_id="c1", source_type="s3",
        config={"bucket_url": "s3://foo"}, table="t",
    )
    r = c.delete("/api/connections/c1")
    assert r.status_code == 409
    assert r.json()["detail"]["referenced_by"]["sources"] == ["s1"]


def test_get_missing_404():
    c = TestClient(app)
    r = c.get("/api/connections/nope")
    assert r.status_code == 404


def test_bulk_delete_mixed_outcomes(fake_stores):
    c = TestClient(app)
    c.post("/api/connections", json=_conn("c1"))
    c.post("/api/connections", json=_conn("c2"))
    c.post("/api/connections", json=_conn("c3"))
    fake_stores["source"]._data["s1"] = Source(
        id="s1", connection_id="c3", source_type="s3",
        config={"bucket_url": "s3://foo"}, table="t",
    )

    r = c.post("/api/connections/bulk-delete", json={"ids": ["c1", "c2", "c3", "ghost"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["deleted"]) == ["c1", "c2"]
    assert body["not_found"] == ["ghost"]
    assert len(body["blocked"]) == 1
    assert body["blocked"][0]["id"] == "c3"
    assert body["blocked"][0]["referenced_by"]["sources"] == ["s1"]


def test_bulk_delete_empty_ids_422():
    c = TestClient(app)
    r = c.post("/api/connections/bulk-delete", json={"ids": []})
    assert r.status_code == 422
