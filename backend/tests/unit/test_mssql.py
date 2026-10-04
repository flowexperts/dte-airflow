"""SQL Server rides the same seams as MySQL (plan 069): one saved
`mssql://` URL serves the source opener, the writer and the probe. No
server is reachable from CI, so every test intercepts at the driver edge."""
from __future__ import annotations

import sys
import types

import ibis
import pandas as pd
import pytest

from dte.engine.writers import write
from dte.models.pipeline import (
    DESTINATION_CONNECTION_COMPAT,
    ENGINE_READ_SUPPORT,
    ENGINE_WRITE_SUPPORT,
    SOURCE_CONNECTION_COMPAT,
    Connection,
    SqlDatabaseTarget,
)

URL = "mssql://sa:p%40ss@db.local:14330/sales?TrustServerCertificate=yes"


def test_connection_type_and_compat():
    conn = Connection(id="m", connection_type="mssql", credentials={"url": URL})
    assert conn.credentials == {"url": URL}
    assert "mssql" in SOURCE_CONNECTION_COMPAT["sql_database"]
    assert "mssql" in DESTINATION_CONNECTION_COMPAT["sql_database"]
    assert ENGINE_READ_SUPPORT["mssql"] == {"mssql"}
    assert "mssql" in ENGINE_WRITE_SUPPORT["duckdb"]


def test_open_mssql_splits_url_for_ibis(monkeypatch):
    from dte.engine import backend_registry as br

    seen: dict = {}
    monkeypatch.setitem(sys.modules, "pyodbc", types.ModuleType("pyodbc"))
    monkeypatch.setattr(
        ibis, "mssql", types.SimpleNamespace(connect=lambda **kw: seen.update(kw)),
        raising=False,
    )
    br._open_ibis_backend(
        Connection(id="m", connection_type="mssql", credentials={"url": URL}),
        {"url": URL},
    )
    assert seen == {
        "host": "db.local",
        "port": 14330,
        "user": "sa",
        "password": "p@ss",
        "database": "sales",
        "driver": "ODBC Driver 18 for SQL Server",
        "TrustServerCertificate": "yes",
    }


def test_open_mssql_driver_overridable_from_url(monkeypatch):
    from dte.engine import backend_registry as br

    seen: dict = {}
    monkeypatch.setitem(sys.modules, "pyodbc", types.ModuleType("pyodbc"))
    monkeypatch.setattr(
        ibis, "mssql", types.SimpleNamespace(connect=lambda **kw: seen.update(kw)),
        raising=False,
    )
    br._open_mssql({"url": "mssql://u:p@h/db?driver=FreeTDS"})
    assert seen["driver"] == "FreeTDS"
    assert seen["port"] == 1433


def test_writer_uses_dlt_mssql_destination(monkeypatch):
    import dlt

    seen: dict = {}
    real = dlt.destinations.mssql

    def _spy(**kw):
        seen.update(kw)
        return real(**kw)

    monkeypatch.setattr(dlt.destinations, "mssql", _spy)
    monkeypatch.setattr(
        dlt, "pipeline", lambda **kw: type("P", (), {"run": lambda s, r: None})()
    )
    con = ibis.duckdb.connect()
    con.create_table("t", pd.DataFrame([{"CustomerID": 1}]), overwrite=True)
    write(
        con.table("t"),
        SqlDatabaseTarget(
            type="sql_database", dialect="mssql", schema="dbo", table="orders"
        ),
        credentials={"url": URL},
    )
    assert seen["credentials"] == URL
    assert seen["naming_convention"] == "direct"


def test_probe_rewrites_url_to_pyodbc(monkeypatch):
    from dte.sources import connection_test as ct

    seen: dict = {}
    monkeypatch.setattr(ct, "_probe_sql_url", lambda creds: seen.update(creds) or {})
    ct.probe_connection(
        Connection(id="m", connection_type="mssql", credentials={"url": URL})
    )
    assert seen["url"] == (
        "mssql+pyodbc://sa:p%40ss@db.local:14330/sales"
        "?TrustServerCertificate=yes&driver=ODBC+Driver+18+for+SQL+Server"
    )
