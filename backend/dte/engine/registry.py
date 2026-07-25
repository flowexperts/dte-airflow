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


def get_engine(name: str) -> BaseEngine:
    """Return a fresh engine instance for *name*.

    Raises
    ------
    ValueError
        Unknown engine name or Trino requested but ``DTE_TRINO_ENABLED`` is
        not ``"true"``.
    """
    if name == "duckdb":
        return DuckDBEngine()

    if name == "trino":
        _trino_enabled = os.environ.get("DTE_TRINO_ENABLED", "false").lower()
        if _trino_enabled != "true":
            raise ValueError(
                "Trino engine is disabled. Set DTE_TRINO_ENABLED=true and "
                "configure DTE_TRINO_HOST / DTE_TRINO_PORT / DTE_TRINO_USER "
                "to enable it."
            )
        from dte.engine.trino_engine import TrinoEngine
        return TrinoEngine()

    raise ValueError(
        f"Unknown engine {name!r}. Available engines: 'duckdb'"
        + (" and 'trino' (when DTE_TRINO_ENABLED=true)" if True else "")
    )
