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
from dte.sources.metered import METERED

_SQL = {"postgres": "postgres", "mysql": "mysql", "mssql": "mssql", "sqlite": "sqlite", "snowflake": "snowflake"}
_STORAGE = {"aws": "s3", "google_cloud_platform": "gcs", "wasb": "azure", "adls": "azure",
            "azure_data_lake": "azure", "sftp": "sftp"}
# Airflow connection extra -> credential key the opener reads (plan 093).
# BigQuery enforces the bytes cap; Snowflake (no bytes cap) the timeout.
_CAPS = {"dte_max_bytes_billed": "max_bytes_billed",
         "dte_statement_timeout_seconds": "statement_timeout_seconds"}
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
    if kind in METERED:
        # Plan 093: per-connection caps, applied by the backend_registry openers.
        for extra_key, cred_key in _CAPS.items():
            if x.get(extra_key):
                creds[cred_key] = int(x[extra_key])
    return Connection.model_construct(id=c.conn_id, name=c.conn_id, connection_type=kind,
                                      credentials=creds)


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


def http_headers(conn_id: str) -> dict[str, str]:
    """Request headers for an `http_lookup` step (plan 085) from an Airflow
    connection: `headers` in its extras, plus the password as a Bearer token.
    A missing connection raises `ModelConnectionMissing`."""
    from airflow.exceptions import AirflowNotFoundException
    from airflow.hooks.base import BaseHook

    try:
        conn = BaseHook.get_connection(conn_id)
    except AirflowNotFoundException:
        raise ModelConnectionMissing(
            f"airflow connection {conn_id!r} not found — create it in Airflow → "
            "Admin → Connections (type 'http', token as password)"
        ) from None
    headers = {str(k): str(v) for k, v in (conn.extra_dejson.get("headers") or {}).items()}
    if conn.password:
        headers.setdefault("Authorization", f"Bearer {conn.password}")
    return headers


# Model keys (plan 072). The official providers' hooks own the conn type, the
# default conn id and client construction (password = key, host = base_url,
# Bedrock/Vertex via extras); DTE only picks the hook.
_MODEL_HOOKS = {
    "claude": ("airflow.providers.anthropic.hooks.anthropic", "AnthropicHook"),
    "openai": ("airflow.providers.openai.hooks.openai", "OpenAIHook"),
}


class ModelConnectionMissing(RuntimeError):
    """The step's model connection does not exist in Airflow."""


def _hook_class(provider: str):
    import importlib

    module, name = _MODEL_HOOKS[provider]
    return getattr(importlib.import_module(module), name)


def model_client(provider: str, conn_id: str | None):
    """The SDK client for `provider`, built from an Airflow connection."""
    from airflow.exceptions import AirflowNotFoundException

    hook_cls = _hook_class(provider)
    conn_id = conn_id or hook_cls.default_conn_name
    try:
        return hook_cls(conn_id=conn_id).get_conn()
    except AirflowNotFoundException:
        raise ModelConnectionMissing(
            f"airflow connection {conn_id!r} not found — create it in Airflow → "
            f"Admin → Connections (type {hook_cls.conn_type!r}, API key as password)"
        ) from None


def model_connections(provider: str) -> list[str]:
    """Conn ids usable by `provider`: every DB connection of its type, plus the
    default when it resolves elsewhere (env var or secrets backend)."""
    from airflow.exceptions import AirflowNotFoundException
    from airflow.hooks.base import BaseHook
    from airflow.models.connection import Connection as AConn
    from airflow.utils.session import create_session
    from sqlalchemy import select

    hook_cls = _hook_class(provider)
    with create_session() as s:
        ids = list(s.scalars(
            select(AConn.conn_id).where(AConn.conn_type == hook_cls.conn_type).order_by(AConn.conn_id)
        ))
    if hook_cls.default_conn_name not in ids:
        try:
            BaseHook.get_connection(hook_cls.default_conn_name)
            ids.insert(0, hook_cls.default_conn_name)
        except AirflowNotFoundException:
            pass
    return ids
