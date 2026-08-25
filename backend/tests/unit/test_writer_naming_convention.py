"""The dlt-backed writers must not normalise the caller's identifiers.

The destination table already exists with declared column names, so the
columns handed to dlt are the ones to write to. Under dlt's default
`snake_case` convention a `CustomerID` column is lowercased, matches
nothing, and is *added* — the run reports rows written while the column
the user mapped to stays null, and nothing raises. A silent wrong-column
write is the worst failure mode in this codebase, so it gets a test that
needs no database.

The destination factory is intercepted rather than connected to, which is
what lets this cover snowflake and bigquery — neither reachable from CI.
"""

import ibis
import pandas as pd
import pytest

from dte.engine.writers import write
from dte.models.pipeline import PostgresTarget, SqlDatabaseTarget


@pytest.fixture
def table():
    con = ibis.duckdb.connect()
    con.create_table(
        "t",
        pd.DataFrame([{"CustomerID": 1, "shipping_date": "2026-01-05"}]),
        overwrite=True,
    )
    return con.table("t")


@pytest.fixture
def captured(monkeypatch):
    """Record what the writer asks dlt for, without connecting to anything."""
    import dlt

    seen: dict = {}

    def _spy(name):
        real = getattr(dlt.destinations, name)

        def _wrapped(**kwargs):
            seen["dialect"] = name
            seen["naming_convention"] = kwargs.get("naming_convention")
            return real(**kwargs)

        return _wrapped

    def _pipeline(**kw):
        seen["pipelines_dir"] = kw.get("pipelines_dir")
        return type("P", (), {"run": lambda self, r: None})()

    # `mysql` is deliberately absent — see test_mysql_dialect_is_broken.
    for name in ("postgres", "snowflake", "bigquery"):
        monkeypatch.setattr(dlt.destinations, name, _spy(name))
    monkeypatch.setattr(dlt, "pipeline", _pipeline)
    return seen


def test_postgres_writer_passes_identifiers_through(table, captured):
    write(
        table,
        PostgresTarget(type="postgres", schema="analytics", table="orders"),
        credentials={"url": "postgresql://u:p@h:5432/db"},
    )
    assert captured["naming_convention"] == "direct"
    # Half a fix without this: dlt persists a normalised schema per
    # pipeline_name, and the stored copy wins over the convention above.
    assert captured["pipelines_dir"] is not None


@pytest.mark.parametrize("dialect", ["snowflake", "bigquery"])
def test_sql_database_writer_passes_identifiers_through(table, captured, dialect):
    write(
        table,
        SqlDatabaseTarget(
            type="sql_database", dialect=dialect, schema="analytics", table="orders"
        ),
        credentials={"url": f"{dialect}://u:p@h/db"},
    )
    assert captured["dialect"] == dialect
    assert captured["naming_convention"] == "direct"
    assert captured["pipelines_dir"] is not None


@pytest.mark.xfail(
    reason="pre-existing, unrelated to naming: `dlt.destinations.mysql` does not "
    "exist in dlt 1.30 (mysql goes through the `sqlalchemy` destination), so a "
    "sql_database destination with dialect='mysql' AttributeErrors at write time. "
    "Fixing it means switching destination impl on a path with no CI coverage — "
    "left for its own change. Delete this xfail when that lands.",
    raises=AttributeError,
    strict=True,
)
def test_mysql_dialect_is_broken(table):
    write(
        table,
        SqlDatabaseTarget(
            type="sql_database", dialect="mysql", schema="analytics", table="orders"
        ),
        credentials={"url": "mysql://u:p@h/db"},
    )
