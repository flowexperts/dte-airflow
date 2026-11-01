"""Cached samples of eager sources for interactive paths (plan 084).

The editor fires schema inference, step schemas and preview on open and on
every edit. An eager source (rest_api, mongodb) copies itself into DuckDB on
each load, so without this every one of those calls re-downloads it. Here
the first call fetches `sample` rows once and writes them to parquet under
`$DTE_ARTIFACT_DIR/samples/` — the volume the api-server and the scheduler
already share — and every later call reads that file.

Metered sources (plan 093, `metered.py`: BigQuery, Snowflake tables) are
cached the same way, fetched with the engine's cheapest primitive, because on
a warehouse a LIMIT bounds rows, not cost. A sidecar `<key>.json` keeps the
table's partition columns, read once with the sample.

Lazy sources (files, object stores, other databases) pass straight through:
they are views or pushdown, so a downstream LIMIT already bounds their work.
Runs never come through here; they read the live source.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import ibis
import pyarrow.parquet as pq

from dte.artifacts import DEFAULT_ARTIFACT_DIR
from dte.sources import metered
from dte.sources.duckdb_secrets import _sql_ident, _sql_string_literal
from dte.sources.loader import EAGER, load_source

# The dataset dlt lands eager sources in. Raw-SQL steps name it
# (`dte_sources.pypi_top`), so the cached view must keep answering to it.
DATASET = "dte_sources"

# ponytail: one lock per sample key, never freed; fine for a few hundred
# sources per api-server process.
_LOCKS: dict[str, threading.Lock] = {}


def sample_path(source, connection, table: str | None = None) -> Path:
    """Where `source`'s sample lives. Any config change is a new key, so an
    edited source fetches fresh instead of serving the old shape."""
    ident = json.dumps(
        [source.source_type, source.config, table, getattr(connection, "id", None)],
        sort_keys=True, default=str,
    )
    key = hashlib.sha256(ident.encode()).hexdigest()
    return Path(os.getenv("DTE_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR)) / "samples" / f"{key}.parquet"


def _fresh(path: Path) -> bool:
    ttl = float(os.getenv("DTE_SAMPLE_TTL_SECONDS", "86400"))
    return path.exists() and time.time() - path.stat().st_mtime < ttl


def _fetch(source, connection, credentials, table, sample: int, path: Path) -> None:
    from dte.engine.backend_registry import BackendRegistry
    from dte.engine.connect import connect_duckdb

    scratch = connect_duckdb()
    t = load_source(source, BackendRegistry(duckdb_con=scratch), connection, credentials,
                    table=table, sample=sample)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    t.to_parquet(tmp)
    os.replace(tmp, path)  # readers never see a half-written file


def _fetch_metered(source, registry, connection, credentials, table, sample: int, path: Path) -> None:
    backend = registry.for_connection(connection, credentials)
    kind, schema = connection.connection_type, source.config.get("schema")
    rows = metered.fetch_sample(backend, kind, schema, table, sample)
    sidecar = {"partition_columns": metered.partition_columns(backend, kind, schema, table)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    pq.write_table(rows, tmp)
    path.with_suffix(".json").write_text(json.dumps(sidecar))
    os.replace(tmp, path)


def sample_info(source, connection, table: str | None) -> dict | None:
    """What the editor shows beside a metered preview, or None when the
    source isn't metered or has no sample yet."""
    if not metered.is_metered(source, connection):
        return None
    path = sample_path(source, connection, table)
    if not path.exists():
        return None
    side = path.with_suffix(".json")
    return {
        "rows": pq.read_metadata(path).num_rows,
        "taken_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        "partition_columns": json.loads(side.read_text())["partition_columns"] if side.exists() else [],
    }


def drop_sample(source, connection, table: str | None) -> bool:
    """Forget a cached sample so the next interactive load fetches afresh."""
    path = sample_path(source, connection, table)
    path.with_suffix(".json").unlink(missing_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def load_interactive(source, registry, connection, credentials, table: str | None = None,
                     *, sample: int) -> ibis.Table:
    """`load_source` for the editor: eager and metered sources come from the
    cached sample, fetched once per key (concurrent misses share one fetch)."""
    if metered.is_metered(source, connection):
        path = sample_path(source, connection, table)
        with _LOCKS.setdefault(path.stem, threading.Lock()):
            if not _fresh(path):
                _fetch_metered(source, registry, connection, credentials, table, sample, path)
        # One view per (source, table): a pipeline may pick several tables
        # off one source. Raw-SQL steps alias their table, so the name is free.
        view = f"{source.id}__{table}"
        con = registry.duckdb()
        con.con.execute(
            f"CREATE OR REPLACE VIEW {_sql_ident(view)} AS "  # nosec B608 — quoted
            f"SELECT * FROM read_parquet({_sql_string_literal(str(path))})"
        )
        return con.table(view)
    if source.source_type not in EAGER:
        return load_source(source, registry, connection, credentials, table=table)

    path = sample_path(source, connection, table)
    with _LOCKS.setdefault(path.stem, threading.Lock()):
        if not _fresh(path):
            _fetch(source, connection, credentials, table, sample, path)

    con = registry.duckdb()
    con.con.execute(f"CREATE SCHEMA IF NOT EXISTS {DATASET}")
    con.con.execute(
        f"CREATE OR REPLACE VIEW {DATASET}.{_sql_ident(source.table)} AS "  # nosec B608 — quoted
        f"SELECT * FROM read_parquet({_sql_string_literal(str(path))})"
    )
    return con.table(source.table, database=("memory", DATASET))
