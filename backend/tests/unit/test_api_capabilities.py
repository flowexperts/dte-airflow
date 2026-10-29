"""The UI offers what the installed Airflow providers support (plan 074)."""
from fastapi.testclient import TestClient

from dte.airflow import connections
from dte.api.main import app


def test_capabilities_follow_installed_providers(monkeypatch):
    monkeypatch.setattr(connections, "available_kinds", lambda: {"local_fs", "postgres", "s3"})
    body = TestClient(app).get("/api/capabilities").json()
    assert body["connection_kinds"]["s3"] == {"available": True, "install": None}
    assert body["connection_kinds"]["mongodb"] == {
        "available": False, "install": "apache-airflow-providers-mongo"}
    assert body["source_kinds"]["s3"] is True
    assert body["source_kinds"]["sql_database"] is True  # via postgres
    assert body["source_kinds"]["mongodb"] is False
    assert body["source_kinds"]["documents"] is True  # local_fs or s3
    assert body["destination_types"]["parquet"] is True
    assert body["destination_types"]["sql_database"] is False  # mysql/mssql/snowflake/bigquery absent
