"""Lightweight connectivity probes for a Connection.

Each probe returns quickly (a few seconds worst-case) and either succeeds
(reports connectivity + version-ish info) or returns a structured error.
The UI's "Test" button on `/connections` uses these to give immediate
feedback before a user wires a Connection into a Source or Destination.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from dte.models.pipeline import Connection


class ProbeResult(dict):
    """`{ok: bool, elapsed_ms: int, detail: str}`."""


def _ok(elapsed: float, detail: str = "") -> ProbeResult:
    return ProbeResult(ok=True, elapsed_ms=int(elapsed * 1000), detail=detail)


def _fail(elapsed: float, detail: str) -> ProbeResult:
    return ProbeResult(ok=False, elapsed_ms=int(elapsed * 1000), detail=detail)


def _probe_local_fs(_creds: dict) -> ProbeResult:
    # Trivial: local_fs is always available.
    return _ok(0.0, "local filesystem")


def _probe_sql_url(creds: dict) -> ProbeResult:
    """Attach via SQLAlchemy and run SELECT 1. Works for postgres, mysql,
    sqlite, snowflake, bigquery — anything with a SQLAlchemy driver."""
    from sqlalchemy import create_engine, text
    url = creds.get("url")
    if not url:
        return _fail(0, "credentials missing 'url'")
    t0 = time.perf_counter()
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return _ok(time.perf_counter() - t0, "SELECT 1 ok")
    except Exception as e:
        return _fail(time.perf_counter() - t0, f"{type(e).__name__}: {e}")


def _probe_mssql(creds: dict) -> ProbeResult:
    """Users save `mssql://…`; SQLAlchemy needs the pyodbc driver and the
    ODBC driver name spelled out."""
    from sqlalchemy.engine import make_url

    from dte.engine.backend_registry import MSSQL_ODBC_DRIVER

    if not creds.get("url"):
        return _fail(0, "credentials missing 'url'")
    url = make_url(creds["url"]).set(drivername="mssql+pyodbc")
    if "driver" not in url.query:
        url = url.update_query_dict({"driver": MSSQL_ODBC_DRIVER})
    return _probe_sql_url({"url": url.render_as_string(hide_password=False)})


def _probe_mongodb(creds: dict) -> ProbeResult:
    url = creds.get("url")
    if not url:
        return _fail(0, "credentials missing 'url'")
    t0 = time.perf_counter()
    try:
        from pymongo import MongoClient
        client = MongoClient(url, serverSelectionTimeoutMS=3000)
        info = client.server_info()
        return _ok(time.perf_counter() - t0, f"MongoDB {info.get('version', '?')}")
    except Exception as e:
        return _fail(time.perf_counter() - t0, f"{type(e).__name__}: {e}")


def _probe_s3(creds: dict) -> ProbeResult:
    """Confirm creds are shaped right and s3fs can build a client."""
    aki = creds.get("aws_access_key_id")
    if not aki:
        return _fail(0, "credentials missing 'aws_access_key_id'")
    t0 = time.perf_counter()
    try:
        import s3fs  # noqa: F401
        # A cheap check — instantiating the FS doesn't hit the network.
        fs = s3fs.S3FileSystem(
            key=aki,
            secret=creds.get("aws_secret_access_key"),
            token=creds.get("aws_session_token"),
            client_kwargs={
                k: v for k, v in {
                    "region_name": creds.get("region_name"),
                    "endpoint_url": creds.get("endpoint_url"),
                }.items() if v
            },
        )
        fs.ls("s3://")  # anonymous list of buckets — will raise if creds broken
        return _ok(time.perf_counter() - t0, "credentials shape ok")
    except Exception as e:
        return _fail(time.perf_counter() - t0, f"{type(e).__name__}: {e}")


def _probe_rest_api(creds: dict) -> ProbeResult:
    """No-op — rest_api creds can only be verified with a specific URL,
    which lives on the Source config, not the Connection."""
    return _ok(0.0, "rest_api probe deferred to source configuration")


def _probe_unknown(_creds: dict) -> ProbeResult:
    return _fail(0.0, "no probe implemented for this connection type")


_PROBES: dict[str, Callable[[dict], ProbeResult]] = {
    "local_fs": _probe_local_fs,
    "s3": _probe_s3,
    "gcs": _probe_unknown,      # GCS probe deferred; DuckDB HMAC hop needs a bucket.
    "azure": _probe_unknown,    # same reasoning.
    "postgres": _probe_sql_url,
    "mysql": _probe_sql_url,
    "mssql": _probe_mssql,
    "sqlite": _probe_sql_url,
    "snowflake": _probe_sql_url,
    "bigquery": _probe_sql_url,
    "mongodb": _probe_mongodb,
    "rest_api": _probe_rest_api,
}


def probe_connection(connection: Connection) -> ProbeResult:
    probe = _PROBES.get(connection.connection_type, _probe_unknown)
    return probe(connection.credentials)
