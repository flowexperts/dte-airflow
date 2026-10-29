"""DuckDB helpers shared by readers and writers: SQL quoting, `{env: …}`
indirection and extension loading. Object-store auth moved to the Airflow
providers (`dte.sources.object_store`, plan 074)."""

from __future__ import annotations

import os
import tempfile
from typing import Any


def resolve_secret(value: Any) -> Any:
    if isinstance(value, dict) and set(value.keys()) == {"env"}:
        return os.environ[value["env"]]
    return value


def _sql_string_literal(s: str) -> str:
    """DuckDB SQL string literal — wrap in '', escape internal ' as ''."""
    return "'" + s.replace("'", "''") + "'"


def _sql_ident(name: str) -> str:
    """DuckDB identifier quote — wrap in "", escape internal " as ""."""
    return '"' + name.replace('"', '""') + '"'


def _secret_kv(key: str, value: str) -> str:
    """Render one `KEY VALUE` line for a DuckDB CREATE SECRET body."""
    return f"    {key} {_sql_string_literal(value)}"


_INSTALLED_EXTS: set[str] = set()


def _ensure_home_directory(raw_con) -> None:
    """Point DuckDB at a writable home before touching extensions.

    DuckDB caches downloaded extensions under `$HOME/.duckdb`. Container
    images commonly run as a user whose home was never created, so `INSTALL`
    dies with "Can't find the home directory at '/home/<user>'" — which would
    take out every s3/gcs/azure read and write. Fall back to a temp dir when
    the configured home is missing or read-only. `DTE_DUCKDB_HOME` overrides.

    This is per *connection*, not per extension: `LOAD` reads the same cache
    `INSTALL` writes, and connections are created per request while
    `_INSTALLED_EXTS` lives for the whole process.
    """
    home = os.environ.get("DTE_DUCKDB_HOME") or os.environ.get("HOME") or ""
    if home and os.path.isdir(home) and os.access(home, os.W_OK):
        return
    fallback = os.path.join(tempfile.gettempdir(), "dte-duckdb-home")
    os.makedirs(fallback, exist_ok=True)
    raw_con.execute(f"SET home_directory={_sql_string_literal(fallback)}")


def _ensure_ext(raw_con, name: str) -> None:
    """Idempotently INSTALL + LOAD a DuckDB extension in this process."""
    _ensure_home_directory(raw_con)
    if name not in _INSTALLED_EXTS:
        raw_con.execute(f"INSTALL {name}")
        _INSTALLED_EXTS.add(name)
    raw_con.execute(f"LOAD {name}")
