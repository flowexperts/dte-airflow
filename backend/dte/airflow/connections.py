"""Airflow Connection -> DTE Connection (plan 074).

The installed provider does the auth. SQL URLs come from the provider hook;
object storage carries only the conn_id and is opened through the provider's
filesystem (`dte.sources.object_store`). A kind is offered only when its
provider (and, for storage, the provider's filesystem) is installed.

`google_cloud_platform` is ambiguous: extra `dte_type` picks "gcs" or "bigquery"
(default gcs). The google provider's own `gcpbigquery` type is always BigQuery.
"""
from __future__ import annotations

import re
from functools import lru_cache

from dte.models.pipeline import Connection

_SQL = {"postgres": "postgres", "mysql": "mysql", "mssql": "mssql", "sqlite": "sqlite", "snowflake": "snowflake"}
_STORAGE = {"aws": "s3", "google_cloud_platform": "gcs", "wasb": "azure", "adls": "azure",
            "azure_data_lake": "azure", "sftp": "sftp"}
# The fsspec scheme each storage kind needs the provider to supply.
STORAGE_SCHEME = {"s3": "s3", "gcs": "gs", "azure": "abfs", "sftp": "sftp"}
# Per DTE kind: the Airflow conn_types that map to it, and what to install
# when none is available (shown in the UI).
KINDS: dict[str, tuple[set[str], str]] = {
    "local_fs": ({"fs"}, "apache-airflow-providers-standard"),
    "postgres": ({"postgres"}, "apache-airflow-providers-postgres"),
    "mysql": ({"mysql"}, "apache-airflow-providers-mysql"),
    "mssql": ({"mssql"}, "apache-airflow-providers-microsoft-mssql"),
    "sqlite": ({"sqlite"}, "apache-airflow-providers-sqlite"),
    "snowflake": ({"snowflake"}, "apache-airflow-providers-snowflake"),
    "bigquery": ({"google_cloud_platform", "gcpbigquery"}, "apache-airflow-providers-google"),
    "mongodb": ({"mongo"}, "apache-airflow-providers-mongo"),
    "rest_api": ({"http"}, "apache-airflow-providers-http"),
    "s3": ({"aws"}, "apache-airflow-providers-amazon[s3fs]"),
    "gcs": ({"google_cloud_platform"}, "apache-airflow-providers-google"),
    "azure": ({"wasb", "adls", "azure_data_lake"}, "apache-airflow-providers-microsoft-azure"),
    "sftp": ({"sftp"}, "apache-airflow-providers-sftp sshfs"),
}


def _plain_scheme(url: str) -> str:
    """`postgresql+psycopg2://…` -> `postgresql://…`: DTE's openers and dlt
    writers want the dialect, not SQLAlchemy's driver."""
    return re.sub(r"^(\w+)\+\w+://", r"\1://", url)


def _hook_url(hook) -> str:
    try:
        url = hook.sqlalchemy_url
    except (AttributeError, NotImplementedError):
        return _plain_scheme(hook.get_uri())
    s = url.render_as_string(hide_password=False) if hasattr(url, "render_as_string") else str(url)
    return _plain_scheme(s)


def from_airflow(c) -> Connection:
    """`c` is an Airflow Connection (or anything with the same attributes)."""
    x, t = c.extra_dejson, c.conn_type
    if t in _SQL:
        kind, creds = _SQL[t], {"url": _hook_url(c.get_hook())}
    elif t == "mongo":
        kind, creds = "mongodb", {"url": c.get_hook().uri}
    elif t == "gcpbigquery" or (t == "google_cloud_platform" and x.get("dte_type") == "bigquery"):
        # The project comes from the hook; credentials are fetched from it at open time.
        kind = "bigquery"
        creds = {"url": f"bigquery://{c.get_hook().project_id}", "conn_id": c.conn_id}
    elif t in _STORAGE:
        kind, creds = _STORAGE[t], {"conn_id": c.conn_id}
    elif t == "http":
        kind = "rest_api"
        auth = ({"type": "http_basic", "username": c.login, "password": c.password} if c.login
                else {"type": "bearer", "token": c.password} if c.password else {})
        creds = {"auth": auth, "headers": x.get("headers") or {}}
    elif t == "fs":
        kind, creds = "local_fs", {}
    else:
        raise ValueError(f"airflow connection type {t!r} has no DTE mapping (conn_id={c.conn_id!r})")
    return Connection.model_construct(id=c.conn_id, name=c.conn_id, connection_type=kind,
                                      credentials=creds, tenant_id="default")


@lru_cache(maxsize=1)
def _installed() -> tuple[set[str], set[str]]:
    """(conn_types with a provider hook, fsspec schemes a provider can open)."""
    import fsspec
    from airflow.providers_manager import ProvidersManager

    conn_types = set(ProvidersManager().hooks)
    schemes = set()
    for scheme in STORAGE_SCHEME.values():
        try:
            fsspec.get_filesystem_class(scheme)  # s3 needs s3fs, gs gcsfs, abfs adlfs, sftp sshfs
            schemes.add(scheme)
        except (ImportError, ValueError):
            pass
    return conn_types, schemes


def available_kinds() -> set[str]:
    conn_types, schemes = _installed()
    return {k for k, (types, _) in KINDS.items()
            if types & conn_types and (k not in STORAGE_SCHEME or STORAGE_SCHEME[k] in schemes)}


def to_dte(conn_id: str) -> tuple[Connection, dict]:
    from airflow.hooks.base import BaseHook  # lazy: airflow is an optional extra

    conn = from_airflow(BaseHook.get_connection(conn_id))
    return conn, conn.credentials
