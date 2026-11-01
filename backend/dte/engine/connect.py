"""The one way DTE opens a DuckDB connection (plan 086).

Unconfigured, every connection assumes it may use 80% of host RAM and every
core — and a worker runs several tasks and previews at once. All
`ibis.duckdb.connect()` calls go through here so the limits apply everywhere.
"""
from __future__ import annotations

import ibis

from dte.config import get_settings


def connect_duckdb() -> ibis.BaseBackend:
    s = get_settings()
    config = {
        "memory_limit": s.duckdb_memory_limit,
        "threads": s.duckdb_threads,
        "temp_directory": s.duckdb_temp_dir,
    }
    return ibis.duckdb.connect(**{k: v for k, v in config.items() if v is not None})
