"""A Postgres-bound result written to a file (plan 086 task 1).

With a single `sql_database` source the compiled table is bound to the native
ibis postgres backend, not the engine's DuckDB connection. The file writer
must stage it through Arrow instead of asking DuckDB for a view over it.
"""
import os
import uuid
from urllib.parse import urlparse

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DTE_DATABASE_URL"), reason="requires DTE_DATABASE_URL"),
]

import ibis
import pyarrow.parquet as pq

from dte.airflow.runner import run_pipeline
from dte.models.pipeline import Connection, Destination, Pipeline, Source, SourceTableRef


def _pg_url() -> str:
    return os.environ["DTE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
def pg_table():
    u = urlparse(_pg_url())
    con = ibis.postgres.connect(host=u.hostname, port=u.port, user=u.username,
                                password=u.password, database=u.path.lstrip("/"))
    name = f"t086_{uuid.uuid4().hex[:8]}"
    con.raw_sql(f'CREATE TABLE "{name}" (id INTEGER, amount INTEGER)')
    con.raw_sql(f'INSERT INTO "{name}" VALUES (1, 10), (2, 20), (3, 30)')
    yield name
    con.raw_sql(f'DROP TABLE IF EXISTS "{name}"')


def test_postgres_source_to_parquet_file(tmp_path, pg_table):
    conn = Connection(id="pg", connection_type="postgres", credentials={"url": _pg_url()})
    src = Source(id="s", connection_id="pg", source_type="sql_database", config={}, table=pg_table)
    ref = SourceTableRef(source_id="s", alias="s", table=pg_table)
    out = tmp_path / "out.parquet"
    dest = Destination(id="d", connection_id="local_fs", dest_type="parquet",
                       config={"type": "parquet", "path": str(out)})
    dest.narrow_config()
    p = Pipeline(id="p", name="p", sources=[ref.model_dump()],
                 steps=[{"op": "filter", "expr": "amount > 10"}], output_id="d")

    res = run_pipeline(p, [(ref, src, conn, conn.credentials)], (dest, {}))

    assert res.status == "completed" and res.rows_written == 2
    assert sorted(pq.read_table(out).column("id").to_pylist()) == [2, 3]
