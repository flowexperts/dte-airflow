"""Airflow Connection -> DTE (Connection, creds). Reads fields/extras only;
no Airflow hooks are wrapped. `gcp` is ambiguous: extra `dte_type` picks
"gcs" or "bigquery" (default: gcs when hmac keys are present, else bigquery)."""
from __future__ import annotations

from urllib.parse import quote, urlencode

from dte.models.pipeline import Connection


def _url(scheme: str, c) -> str:
    auth = f"{quote(c.login or '')}:{quote(c.password or '')}@" if c.login else ""
    port = f":{c.port}" if c.port else ""
    return f"{scheme}://{auth}{c.host or ''}{port}/{c.schema or ''}"


def from_airflow(c) -> Connection:
    """`c` is an Airflow Connection (or anything with the same attributes)."""
    x = c.extra_dejson
    t = c.conn_type
    if t == "postgres":
        kind, creds = "postgres", {"url": _url("postgresql", c)}
    elif t == "mysql":
        kind, creds = "mysql", {"url": _url("mysql", c)}
    elif t == "mssql":
        # Extras (TrustServerCertificate, Encrypt, driver, …) become ODBC
        # options on the URL; `sqlalchemy_scheme` is the provider's own knob.
        q = urlencode({k: v for k, v in x.items() if k != "sqlalchemy_scheme"})
        kind, creds = "mssql", {"url": _url("mssql", c) + (f"?{q}" if q else "")}
    elif t == "sqlite":
        kind, creds = "sqlite", {"url": f"sqlite:///{c.host}"}
    elif t == "snowflake":
        q = "&".join(f"{k}={x[k]}" for k in ("warehouse", "role") if x.get(k))
        kind, creds = "snowflake", {"url": f"snowflake://{quote(c.login or '')}:{quote(c.password or '')}@{x['account']}/{c.schema or ''}" + (f"?{q}" if q else "")}
    elif t == "mongo":
        kind, creds = "mongodb", {"url": _url("mongodb", c)}
    elif t == "google_cloud_platform":
        kind = x.get("dte_type") or ("gcs" if x.get("hmac_key_id") else "bigquery")
        if kind == "gcs":
            creds = {k: x[k] for k in ("hmac_key_id", "hmac_secret", "endpoint_url") if x.get(k)}
        else:
            creds = {"url": f"bigquery://{x['project']}"}
    elif t == "aws":
        kind = "s3"
        creds = {"aws_access_key_id": c.login, "aws_secret_access_key": c.password}
        creds.update({k: x[k] for k in ("aws_session_token", "region_name", "endpoint_url") if x.get(k)})
    elif t == "wasb":
        kind = "azure"
        creds = {"connection_string": x["connection_string"]} if x.get("connection_string") else {
            "azure_storage_account_name": c.login, "azure_storage_account_key": c.password}
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


def to_dte(conn_id: str) -> tuple[Connection, dict]:
    from airflow.hooks.base import BaseHook  # lazy: airflow is an optional extra

    conn = from_airflow(BaseHook.get_connection(conn_id))
    return conn, conn.credentials


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
    from sqlalchemy import select

    from airflow.exceptions import AirflowNotFoundException
    from airflow.hooks.base import BaseHook
    from airflow.models.connection import Connection as AConn
    from airflow.utils.session import create_session

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
