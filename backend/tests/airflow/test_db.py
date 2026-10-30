"""Airflow 3 hides its metadata DB URL from DAG parsing and tasks (plan 073)."""
import sys
from types import ModuleType, SimpleNamespace

import pytest

from dte.airflow.db import sync_url


def test_hidden_airflow_db_url_names_database_url(monkeypatch):
    monkeypatch.delenv("DTE_DATABASE_URL", raising=False)
    fake = ModuleType("airflow.configuration")
    fake.conf = SimpleNamespace(get=lambda *_: "airflow-db-not-allowed:///")
    monkeypatch.setitem(sys.modules, "airflow", ModuleType("airflow"))
    monkeypatch.setitem(sys.modules, "airflow.configuration", fake)
    with pytest.raises(RuntimeError, match="DTE_DATABASE_URL"):
        sync_url()


def test_database_url_wins(monkeypatch):
    monkeypatch.setenv("DTE_DATABASE_URL", "postgres://u:p@h/db")
    assert sync_url() == "postgresql+psycopg2://u:p@h/db"
