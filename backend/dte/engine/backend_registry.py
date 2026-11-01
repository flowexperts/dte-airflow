"""Per-request cache of ibis backends keyed by Connection.id.

Purpose: source loaders no longer funnel every table through a single shared
DuckDB backend.  Sources that reference a real DB connection (postgres,
mysql, sqlite, bigquery, snowflake) get an ibis-native backend for that
dialect so subsequent compilation pushes down into the source engine.
Filesystem-family sources still use a shared in-process DuckDB.

Sharing rule: two sources on the same Connection.id share one backend
instance (so the compiler sees them as living on the same backend and can
join them without federation).  Two Connections of the same type but with
different ids get separate backends.

Lifetime: one registry per request/run.  Not a process-global cache — a
long-lived pool would leak connections and blur tenant boundaries.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, unquote, urlparse

import ibis

from dte.sources.loader import resolve_secret

if TYPE_CHECKING:
    from dte.models.pipeline import Connection


# The one ODBC driver the image installs (Dockerfile.airflow). ibis and dlt
# both talk to SQL Server through pyodbc, so they share it.
MSSQL_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"


class BackendRegistry:
    """Cache of ibis backends by Connection.id.

    Parameters
    ----------
    duckdb_con
        Optional pre-existing DuckDB backend to reuse (e.g. an engine's
        `.con`).  When omitted, a fresh in-memory DuckDB is opened on
        first `duckdb()` call.
    """

    def __init__(self, duckdb_con: ibis.BaseBackend | None = None):
        self._duckdb: ibis.BaseBackend | None = duckdb_con
        self._by_conn_id: dict[str, ibis.BaseBackend] = {}

    def duckdb(self) -> ibis.BaseBackend:
        """Shared in-process DuckDB backend.

        Used by filesystem-family loaders and dlt-hop loaders (mongodb,
        rest_api) that need somewhere to land extracted rows.
        """
        if self._duckdb is None:
            from dte.engine.connect import connect_duckdb
            self._duckdb = connect_duckdb()
        return self._duckdb

    def for_connection(
        self, connection: Connection, credentials: dict
    ) -> ibis.BaseBackend:
        """Return a cached ibis backend for a DB connection.

        First call opens the connection; later calls (same connection.id)
        reuse the same backend instance.  Raises `NotImplementedError` if
        the connection type has no native ibis backend mapping.
        """
        cached = self._by_conn_id.get(connection.id)
        if cached is not None:
            return cached
        backend = _open_ibis_backend(connection, credentials)
        self._by_conn_id[connection.id] = backend
        return backend


# ─── Dispatch: Connection → ibis backend ─────────────────────────────────


def _open_ibis_backend(connection: Connection, credentials: dict) -> ibis.BaseBackend:
    ctype = connection.connection_type
    opener = _OPENERS.get(ctype)
    if opener is None:
        raise NotImplementedError(
            f"No native ibis backend for connection type {ctype!r}. "
            "Filesystem-family and dlt-hop sources should use "
            "BackendRegistry.duckdb() instead."
        )
    return opener(credentials)


def _open_postgres(credentials: dict) -> ibis.BaseBackend:
    url = resolve_secret(credentials["url"])
    parsed = urlparse(url)
    return ibis.postgres.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        database=(parsed.path or "").lstrip("/") or None,
    )


def _open_mysql(credentials: dict) -> ibis.BaseBackend:
    try:
        import MySQLdb  # noqa: F401  (aka mysqlclient)
    except ImportError as e:
        raise RuntimeError(
            "MySQL source support requires the `mysql-source` extra: "
            "`uv pip install -e '.[mysql-source]'`."
        ) from e
    url = resolve_secret(credentials["url"])
    parsed = urlparse(url)
    return ibis.mysql.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 3306,
        user=parsed.username,
        password=parsed.password,
        database=(parsed.path or "").lstrip("/") or None,
    )


def _open_mssql(credentials: dict) -> ibis.BaseBackend:
    try:
        import pyodbc  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "SQL Server support requires the `mssql` extra and Microsoft's "
            "ODBC Driver 18: `uv pip install -e '.[mssql]'`."
        ) from e
    url = resolve_secret(credentials["url"])
    parsed = urlparse(url)
    # Query params (TrustServerCertificate=yes, Encrypt=…, driver=…) go to
    # pyodbc as-is, so TLS and auth options need no extra form fields.
    params = dict(parse_qsl(parsed.query))
    return ibis.mssql.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 1433,
        user=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
        database=(parsed.path or "").lstrip("/") or None,
        driver=params.pop("driver", MSSQL_ODBC_DRIVER),
        **params,
    )


def _open_sqlite(credentials: dict) -> ibis.BaseBackend:
    url = resolve_secret(credentials["url"])
    # sqlite:///abs/path or sqlite:///:memory:
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
    else:
        path = url
    return ibis.sqlite.connect(path)


def _gcp_credentials(conn_id: str):
    """The google provider's credentials for an Airflow connection: service
    account, workload identity, impersonation — whatever the hook resolves."""
    from airflow.providers.google.common.hooks.base_google import GoogleBaseHook

    return GoogleBaseHook(gcp_conn_id=conn_id).get_credentials()


def _open_bigquery(credentials: dict) -> ibis.BaseBackend:
    # dlt's ConnectionStringCredentials collapses BigQuery creds to a URL like
    # `bigquery://<project>/<dataset>` when possible.  For richer auth
    # (service-account JSON) we accept a `credentials_json` key.
    try:
        import google.cloud.bigquery  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "BigQuery source support requires the `bigquery-source` extra: "
            "`uv pip install -e '.[bigquery-source]'`."
        ) from e
    url = resolve_secret(credentials["url"]) if "url" in credentials else None
    if url:
        parsed = urlparse(url)
        project = parsed.hostname
        dataset = (parsed.path or "").lstrip("/")  # ibis wants "" for none, not None
        extra = {"credentials": _gcp_credentials(credentials["conn_id"])} if credentials.get("conn_id") else {}
        return ibis.bigquery.connect(project_id=project, dataset_id=dataset, **extra)
    project = resolve_secret(credentials["project_id"])
    dataset = resolve_secret(credentials.get("dataset_id")) if credentials.get("dataset_id") else ""
    return ibis.bigquery.connect(project_id=project, dataset_id=dataset)


def _open_snowflake(credentials: dict) -> ibis.BaseBackend:
    try:
        import snowflake.connector  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "Snowflake source support requires the `snowflake-source` extra: "
            "`uv pip install -e '.[snowflake-source]'`."
        ) from e
    url = resolve_secret(credentials["url"])
    return ibis.snowflake.connect(url)


_OPENERS = {
    "postgres": _open_postgres,
    "mysql": _open_mysql,
    "mssql": _open_mssql,
    "sqlite": _open_sqlite,
    "bigquery": _open_bigquery,
    "snowflake": _open_snowflake,
}
