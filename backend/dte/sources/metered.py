"""Metered sources: warehouses that bill per query (plan 093).

On BigQuery (bytes scanned) and Snowflake (warehouse time) a LIMIT does not
make a query cheap, so the builder must not push every edit down live.
Everything engine-specific lives here:

- `fetch_sample`: the cheapest way to get N rows, cached by `sample.py`.
- `partition_columns`: what a filter should touch so a run doesn't scan it all.
- `estimate_bytes`: what a query will scan, without running it.
- `cap_message`: a cap the connection set was hit — say so in plain words.

`kind` is the DTE connection type. Engines DTE has no source kind for
(Databricks, Trino, ClickHouse, Redshift) fall through to LIMIT / no estimate.
"""
from __future__ import annotations

import json
import re
from typing import NamedTuple

METERED = frozenset({"bigquery", "snowflake"})

# BigQuery on-demand list price per TiB scanned. An estimate, not a bill:
# editions/flat-rate customers pay nothing per query.
USD_PER_TIB = {"bigquery": 6.25}

# Below these a run starts without asking: a prompt on every run trains people
# to click through it. BigQuery: ~$1 at list price. Snowflake bills warehouse
# time, so bytes only stand in for "big enough to run a while". An Airflow
# connection overrides both with `dte_confirm_above_bytes`.
CONFIRM_ABOVE_BYTES = {"bigquery": 160 * 2**30, "snowflake": 10 * 2**30}
_NAMES = {"bigquery": "BigQuery", "snowflake": "Snowflake"}

# ponytail: fixed 1% block sample; size it from row count if big tables come
# back sparse or small ones keep hitting the LIMIT fallback.
_BLOCK_SAMPLE_FRACTION = 0.01


class QueryCapExceeded(RuntimeError):
    """A query hit the cap its Airflow connection sets."""


def is_metered(source, connection) -> bool:
    return (getattr(source, "source_type", None) == "sql_database"
            and getattr(connection, "connection_type", None) in METERED)


def _bq_table_id(schema: str | None, table: str) -> str:
    # The source schema is `project.dataset` or `dataset` (billing project).
    return f"{schema}.{table}" if schema else table


def fetch_sample(backend, kind: str, schema: str | None, table: str, n: int):
    """Up to `n` rows of `schema.table` as a pyarrow Table, the cheap way."""
    if kind == "bigquery":
        # tabledata.list: reads storage directly, billed as nothing.
        return backend.client.list_rows(_bq_table_id(schema, table), max_results=n).to_arrow()
    t = backend.table(table, database=schema) if schema else backend.table(table)
    if kind == "snowflake":
        # Block sampling skips micro-partitions instead of scanning them.
        got = t.sample(_BLOCK_SAMPLE_FRACTION, method="block").limit(n).to_pyarrow()
        if got.num_rows >= n:
            return got
        # Short means the table is small, where LIMIT is cheap anyway.
    return t.limit(n).to_pyarrow()


def partition_columns(backend, kind: str, schema: str | None, table: str) -> list[str]:
    """Columns a filter must touch to prune partitions. Metadata only."""
    if kind != "bigquery":
        return []
    t = backend.client.get_table(_bq_table_id(schema, table))
    cols = []
    if t.time_partitioning is not None:
        # No field = ingestion-time partitioning on the pseudo-column.
        cols.append(t.time_partitioning.field or "_PARTITIONTIME")
    if t.range_partitioning is not None:
        cols.append(t.range_partitioning.field)
    return cols


def estimate_bytes(backend, kind: str, sql: str) -> int | None:
    """Bytes `sql` would scan, without running it. None when the engine has
    no cheap estimate."""
    if kind == "bigquery":
        from google.cloud import bigquery as bq

        job = backend.client.query(sql, job_config=bq.QueryJobConfig(dry_run=True, use_query_cache=False))
        return int(job.total_bytes_processed or 0)
    if kind == "snowflake":
        # EXPLAIN compiles only; no warehouse time.
        cur = backend.raw_sql(f"EXPLAIN USING JSON {sql}")
        try:
            plan = json.loads(cur.fetchone()[0])
        finally:
            cur.close()
        return int(plan["GlobalStats"]["bytesAssigned"])
    return None


def est_cost_usd(kind: str, nbytes: int | None) -> float | None:
    rate = USD_PER_TIB.get(kind)
    return None if rate is None or nbytes is None else nbytes / 2**40 * rate


class Verdict(NamedTuple):
    needs_confirm: bool
    blocked: bool
    message: str


def _duration(seconds: int) -> str:
    if seconds % 3600 == 0:
        n, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        n, unit = seconds // 60, "minute"
    else:
        n, unit = seconds, "second"
    return f"{n} {unit}{'' if n == 1 else 's'}"


def judge(kind: str, nbytes: int | None, usd: float | None, *, cap: int | None = None,
          confirm_above: int | None = None, warehouse: str | None = None,
          timeout_seconds: int | None = None) -> Verdict:
    """Whether a run should ask first, and what to tell a person who doesn't
    think in bytes: money on BigQuery, warehouse time on Snowflake."""
    name = _NAMES.get(kind, kind)
    if nbytes is None:
        return Verdict(False, False, "")
    if cap is not None and nbytes > cap:
        return Verdict(True, True, (
            f"This run would read about {fmt_bytes(nbytes)}, more than the {fmt_bytes(cap)} this "
            f"connection allows, so {name} will refuse it. Add a filter so it reads less, or ask an "
            "admin to raise the limit."))
    threshold = confirm_above if confirm_above is not None else CONFIRM_ABOVE_BYTES.get(kind, 0)
    big = nbytes > threshold
    wh = warehouse or "its"
    if usd is not None:
        price = "less than a cent" if usd < 0.01 else f"${usd:,.2f}"
        message = f"This run will cost about {price} on {name}."
    elif big:
        limit = (f"stops a query after {_duration(timeout_seconds)}" if timeout_seconds
                 else "sets no time limit")
        message = (f"This is a large query: it reads about {fmt_bytes(nbytes)}. {name} bills for "
                   f"every minute the {wh} warehouse runs, and this connection {limit}.")
    else:
        message = f"A small query: it reads about {fmt_bytes(nbytes)} on the {wh} warehouse."
    return Verdict(big, False, message)


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""  # unreachable


_BQ_CAP = re.compile(r"limit for bytes billed: (\d+)\. (\d+) or higher required")
_SF_TIMEOUT = re.compile(r"statement or warehouse timeout of (\d+) second")


def cap_message(exc: BaseException) -> str | None:
    """Plain words for a cap the connection set, or None if `exc` is not one."""
    s = str(exc)
    if m := _BQ_CAP.search(s):
        cap, need = int(m.group(1)), int(m.group(2))
        return (f"Query needs at least {fmt_bytes(need)} billed, above this connection's cap of "
                f"{fmt_bytes(cap)} (dte_max_bytes_billed on the Airflow connection). Filter on the "
                "partition column to scan less, or raise the cap.")
    if m := _SF_TIMEOUT.search(s):
        return (f"Query stopped at this connection's {m.group(1)}s statement timeout "
                "(dte_statement_timeout_seconds on the Airflow connection).")
    return None
