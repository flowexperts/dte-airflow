"""Trino execution engine — plan-034 distributed execution seam.

MVP: ibis-trino backend for pure-ibis pipelines.  Raw SQL escape hatches
(filter Advanced tab, expression map) are explicitly rejected because DuckDB
SQL is not portable to Trino (option-a from plan-034).

Pivot step is out of scope for MVP — DuckDB's dynamic PIVOT syntax cannot be
compiled to Trino SQL without significant extra work.  Pipelines that contain
a ``pivot`` step will fail at compile time when run against the Trino engine.

Connection is configured via constructor kwargs or environment variables:
  DTE_TRINO_HOST / DTE_TRINO_PORT / DTE_TRINO_USER / DTE_TRINO_CATALOG /
  DTE_TRINO_DATABASE / DTE_TRINO_PASSWORD.
"""
from __future__ import annotations

import os

import ibis

from dte.engine.base import BaseEngine, EnrichmentSpec
from dte.engine.writers import WriteResult
from dte.engine.writers import write as _write


class TrinoRawSqlNotSupported(RuntimeError):
    """Raised when a pipeline step tries to execute raw DuckDB SQL on Trino.

    DuckDB SQL dialect != Trino SQL dialect.  Plan-034 option-a: reject rather
    than silently produce wrong results.  Switch to Basic filter + typed step
    ops for Trino compatibility, or run the pipeline on the DuckDB engine.
    """


class EnrichmentNotSupportedOnBackend(RuntimeError):
    """Raised when an enrichment step (extract / structure / embed) runs on a
    backend that cannot execute a Python mapper over its rows.

    Enrichment materialises the table and maps it row by row in the API/worker
    process. On a pushdown engine that would mean dragging the whole result
    set out of the cluster, silently discarding the reason to use it. Same
    refusal shape as `TrinoRawSqlNotSupported`: reject rather than do
    something surprising.
    """


class TrinoEngine(BaseEngine):
    """Ibis-backed Trino execution engine.

    Connects via ``ibis.trino.connect()``.  For unit tests the connection is
    mocked at the ibis level so no real cluster is needed.

    Parameters
    ----------
    host, port, user, password, catalog, database
        Trino connection parameters.  Defaults come from ``DTE_TRINO_*`` env
        vars so the engine can be constructed from the registry without extra
        plumbing.
    """

    dialect = "trino"

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        catalog: str | None = None,
        database: str | None = None,
    ):
        _host = host or os.environ.get("DTE_TRINO_HOST", "localhost")
        _port = int(port or os.environ.get("DTE_TRINO_PORT", "8080"))
        _user = user or os.environ.get("DTE_TRINO_USER", "trino")
        _password = password or os.environ.get("DTE_TRINO_PASSWORD")
        _catalog = catalog or os.environ.get("DTE_TRINO_CATALOG", "hive")
        _database = database or os.environ.get("DTE_TRINO_DATABASE", "default")

        self._con = ibis.trino.connect(
            host=_host,
            port=_port,
            user=_user,
            password=_password,
            database=_catalog,
            schema=_database,
        )

    @property
    def con(self) -> ibis.BaseBackend:
        return self._con

    # ------------------------------------------------------------------
    # Raw-SQL escape hatches — rejected for Trino (plan-034 option-a)
    # ------------------------------------------------------------------

    def apply_filter_sql(self, table: ibis.Table, expr: str) -> ibis.Table:  # noqa: ARG002
        raise TrinoRawSqlNotSupported(
            "Raw SQL filter expressions are not supported on the Trino engine. "
            "DuckDB SQL dialect != Trino SQL.  Use the Basic filter tab or "
            "switch this pipeline to the 'duckdb' engine."
        )

    def apply_expression_sql(
        self, table: ibis.Table, output_field: str, expr: str  # noqa: ARG002
    ) -> ibis.Table:
        raise TrinoRawSqlNotSupported(
            "Raw SQL expression maps are not supported on the Trino engine. "
            "DuckDB SQL dialect != Trino SQL.  Use a 'map/lookup' step or "
            "switch this pipeline to the 'duckdb' engine."
        )

    # ------------------------------------------------------------------
    # Execution — same write-layer as DuckDB, ibis handles the dialect
    # ------------------------------------------------------------------

    def apply_enrichment(  # noqa: D102 — see EnrichmentNotSupportedOnBackend
        self, table: ibis.Table, spec: EnrichmentSpec
    ) -> ibis.Table:
        raise EnrichmentNotSupportedOnBackend(
            f"Enrichment step {spec.name!r} cannot run on Trino: it materialises "
            "the table and maps rows in Python, which would pull the whole "
            "result set out of the cluster. Run document pipelines on the "
            "DuckDB engine."
        )

    def execute(
        self,
        table: ibis.Table,
        target,
        credentials: dict | None = None,
        run_id: str | None = None,
    ) -> WriteResult:
        # Enrichment is unsupported here, so there are no system columns to
        # split; `run_id` is accepted only to keep the engine interface one
        # shape.
        return _write(table, target, self._con, credentials=credentials, run_id=run_id)
