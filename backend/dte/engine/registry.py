"""Engine registry — plan-034 dispatch.

``get_engine(name)`` is the single call site used by pipeline routes to obtain
an engine instance.  DuckDB is always available.  Trino is behind the
``DTE_TRINO_ENABLED`` feature flag (default off) so it has zero runtime cost
until a design-partner customer opts in.

Environment variables consumed when Trino is enabled:
  DTE_TRINO_HOST, DTE_TRINO_PORT, DTE_TRINO_USER, DTE_TRINO_PASSWORD,
  DTE_TRINO_CATALOG, DTE_TRINO_DATABASE
"""
from __future__ import annotations

import os

from dte.engine.base import BaseEngine
from dte.engine.duckdb_engine import DuckDBEngine


def trino_enabled() -> bool:
    """Whether the Trino engine is enabled in the current deployment.

    Exposed so validators can raise a helpful 422 (``code=trino_not_enabled``)
    before an engine-selection error surfaces from ``get_engine``.
    """
    return os.environ.get("DTE_TRINO_ENABLED", "false").lower() == "true"


def get_engine(name: str) -> BaseEngine:
    """Return a fresh engine instance for *name*.

    Engine names understood:

    - ``"duckdb"`` — DuckDBEngine (default, also used as the local
      execution glue for filesystem writers).
    - ``"postgres"`` / ``"mysql"`` / ``"sqlite"`` / ``"bigquery"`` /
      ``"snowflake"`` — pushdown engines.  These resolve to a DuckDBEngine
      instance today; the actual pushdown happens because the source
      tables are bound to their native ibis backend by
      :class:`~dte.engine.backend_registry.BackendRegistry` before the
      compiler runs.  DuckDBEngine is retained for writer glue and for the
      raw-SQL escape hatches, which ride on each table's own backend via a
      CTE alias and are transpiled from DuckDB dialect by sqlglot.
    - ``"trino"`` — TrinoEngine, gated behind ``DTE_TRINO_ENABLED``.

    Raises
    ------
    ValueError
        Unknown engine name, or Trino requested but ``DTE_TRINO_ENABLED``
        is not ``"true"``.
    """
    if name == "trino":
        if not trino_enabled():
            raise ValueError(
                "Trino engine is disabled. Set DTE_TRINO_ENABLED=true and "
                "configure DTE_TRINO_HOST / DTE_TRINO_PORT / DTE_TRINO_USER "
                "to enable it."
            )
        from dte.engine.trino_engine import TrinoEngine
        return TrinoEngine()

    _PUSHDOWN_ENGINES = {
        "duckdb", "postgres", "mysql", "sqlite", "bigquery", "snowflake", "auto",
    }
    if name in _PUSHDOWN_ENGINES:
        # BackendRegistry decides the *actual* per-source execution locus;
        # DuckDBEngine is the local orchestrator + writer glue.
        return DuckDBEngine()

    raise ValueError(
        f"Unknown engine {name!r}. Available: duckdb, postgres, mysql, "
        "sqlite, bigquery, snowflake, trino (when DTE_TRINO_ENABLED=true)."
    )
