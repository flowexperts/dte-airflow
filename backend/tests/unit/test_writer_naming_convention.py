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

    # `sqlalchemy`, not `mysql`: dlt ships no mysql destination, so the
    # writer routes the mysql dialect through the sqlalchemy one.
    for name in ("postgres", "snowflake", "bigquery", "sqlalchemy"):
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


def test_mysql_routes_through_the_sqlalchemy_destination(table, captured):
    """dlt has no mysql destination — `dlt.destinations.mysql` raised
    AttributeError at write time, after the destination had saved and
    previewed cleanly. sqlalchemy is dlt's driver layer, not a target
    anyone picks: the dialect stays `mysql` and this mapping is internal."""
    write(
        table,
        SqlDatabaseTarget(
            type="sql_database", dialect="mysql", schema="analytics", table="orders"
        ),
        credentials={"url": "mysql://u:p@h/db"},
    )
    assert captured["dialect"] == "sqlalchemy"
    assert captured["naming_convention"] == "direct"
    assert captured["pipelines_dir"] is not None


def test_mysql_url_keeps_the_scheme_the_user_saved(table, captured, monkeypatch):
    """A bare `mysql://` is SQLAlchemy-speak for the mysqldb driver, which
    needs a C toolchain. Which driver we use is ours to pick, so the writer
    rewrites the scheme rather than making users type `mysql+pymysql://` in
    a connection the source side reads as plain `mysql://`."""
    import dlt

    seen_url = {}
    real = dlt.destinations.sqlalchemy
    monkeypatch.setattr(
        dlt.destinations,
        "sqlalchemy",
        lambda **kw: (seen_url.update(url=kw["credentials"]), real(**kw))[1],
    )
    write(
        table,
        SqlDatabaseTarget(
            type="sql_database", dialect="mysql", schema="analytics", table="orders"
        ),
        credentials={"url": "mysql://u:p@h/db"},
    )
    assert seen_url["url"] == "mysql+pymysql://u:p@h/db"
