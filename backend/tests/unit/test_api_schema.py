import json
from fastapi.testclient import TestClient

from dte.api.main import app


def test_schema_infer_returns_fields(tmp_path):
    data = [{"user_id": 1, "name": "alice"}, {"user_id": 2, "name": "bob"}]
    f = tmp_path / "users.json"
    f.write_text(json.dumps(data))

    payload = {
        "id": "s1", "connection_id": "local_fs",
        "source_type": "filesystem",
        "config": {"bucket_url": str(tmp_path), "file_glob": "users.json"},
        "table": "users",
    }

    client = TestClient(app)
    r = client.post("/api/schema/infer", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert "fields" in body
    names = {f["name"] for f in body["fields"]}
    assert {"user_id", "name"}.issubset(names)
    for f in body["fields"]:
        assert isinstance(f["type"], str)
        assert f["type"]


def test_schema_infer_returns_nested_tree(tmp_path):
    data = [
        {
            "id": "o1",
            "order": {"amount": 100, "currency": "USD"},
            "user": {"address": {"city": "NYC"}},
        }
    ]
    f = tmp_path / "orders.json"
    f.write_text(json.dumps(data))

    payload = {
        "id": "s_nested", "connection_id": "local_fs",
        "source_type": "filesystem",
        "config": {"bucket_url": str(tmp_path), "file_glob": "orders.json"},
        "table": "orders",
    }

    client = TestClient(app)
    r = client.post("/api/schema/infer", json=payload)
    assert r.status_code == 200
    body = r.json()

    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["order"]["type"] == "struct"
    order_kids = {c["name"]: c for c in by_name["order"]["children"]}
    assert set(order_kids) == {"amount", "currency"}
    assert order_kids["amount"]["children"] is None

    user_addr = {c["name"]: c for c in by_name["user"]["children"]}["address"]
    assert user_addr["type"] == "struct"
    assert {c["name"] for c in user_addr["children"]} == {"city"}


def test_schema_infer_missing_source_returns_422(tmp_path):
    payload = {
        "id": "s2", "connection_id": "local_fs",
        "source_type": "filesystem",
        "config": {"bucket_url": str(tmp_path / "nonexistent"), "file_glob": "*.json"},
        "table": "missing",
    }
    client = TestClient(app)
    r = client.post("/api/schema/infer", json=payload)
    assert r.status_code == 422
