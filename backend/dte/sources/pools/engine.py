"""DuckDB engine singleton pool.

A single DuckDBEngine is shared across all pipeline runs in the same process.
Extensions are installed once (idempotent in DuckDB) rather than on every run.

Under the DTE_CONNECTION_POOL_ENABLED feature flag (default: false).

See plans/028-connection-pooling.md — DuckDB scanner extensions section.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dte.engine.duckdb_engine import DuckDBEngine as _DuckDBEngine

# Feature flag — same env var as the mongo pool.
_pool_enabled: bool = os.getenv("DTE_CONNECTION_POOL_ENABLED", "false").lower() in ("1", "true", "yes")

_engine: _DuckDBEngine | None = None


def reset_engine() -> None:
    """Clear the singleton.  Test utility — does not close the underlying connection."""
    global _engine
    _engine = None


def get_engine() -> _DuckDBEngine:
    """Return the process-wide DuckDBEngine, creating it on first use.

    When the pool is disabled a fresh engine is returned on each call (the
    previous behaviour).

    When the pool is enabled the engine is created once; extensions are
    installed at that time.  ``CREATE OR REPLACE VIEW`` per source still
    runs on each run — that is cheap and unavoidable because view definitions
    depend on the run's source config.
    """
    global _engine
    from dte.engine.duckdb_engine import DuckDBEngine

    if not _pool_enabled:
        return DuckDBEngine()

    if _engine is None:
        _engine = DuckDBEngine()
    return _engine
