"""DuckDB object-store plumbing shared by readers and writers.

Extracted from `dte.sources.loader` so `dte.engine.writers` can create the
same scoped SECRETs the loaders do without importing loader internals.
`loader` re-exports every name here, so existing imports keep working.

The three `_build_*_secret_sql` builders are the single place that knows how
a Connection's credential dict maps onto DuckDB's `CREATE SECRET` grammar —
including the endpoint overrides that point at local emulators (MinIO,
fake-gcs-server, Azurite).
"""

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


def _build_s3_secret_sql(credentials: dict, secret_name: str) -> str:
    """Return `CREATE OR REPLACE SECRET …` DDL for an S3-compatible endpoint.

    `credentials` comes from the linked Connection (already decrypted by
    the SecretResolver). Env-indirection is a no-op here — the resolver
    handled it — but `resolve_secret()` is still safe on literals.
    Endpoint URL (LocalStack / MinIO) switches on path-style + optional
    TLS off when the scheme is http.
    """
    parts: list[str] = ["TYPE s3"]
    if "aws_access_key_id" in credentials:
        parts.append(_secret_kv("KEY_ID", resolve_secret(credentials["aws_access_key_id"])))
    if "aws_secret_access_key" in credentials:
        parts.append(_secret_kv("SECRET", resolve_secret(credentials["aws_secret_access_key"])))
    if "aws_session_token" in credentials:
        parts.append(_secret_kv("SESSION_TOKEN", resolve_secret(credentials["aws_session_token"])))
    if "region_name" in credentials:
        parts.append(_secret_kv("REGION", resolve_secret(credentials["region_name"])))
    if "endpoint_url" in credentials:
        endpoint = resolve_secret(credentials["endpoint_url"])
        # Strip scheme — DuckDB wants `host[:port]`.
        stripped = endpoint.split("://", 1)[-1].rstrip("/")
        parts.append(_secret_kv("ENDPOINT", stripped))
        parts.append("    URL_STYLE 'path'")
        if endpoint.startswith("http://"):
            parts.append("    USE_SSL false")
    body = ",\n".join(parts)
    return f"CREATE OR REPLACE SECRET {_sql_ident(secret_name)} (\n{body}\n)"


def _build_gcs_secret_sql(credentials: dict, secret_name: str) -> str:
    """DuckDB uses HMAC keys for GCS via the S3-compatible API — not the
    service-account JSON that fsspec/gcsfs consumes. `credentials_json`
    is rejected; users must issue HMAC keys instead.

    `endpoint_url` overrides the GCS endpoint (e.g. fake-gcs-server for
    local testing). DuckDB's TYPE gcs supports ENDPOINT, USE_SSL, URL_STYLE."""
    if "credentials_json" in credentials and "hmac_key_id" not in credentials:
        raise ValueError(
            "gcs connection: `credentials_json` (service-account JSON) is not "
            "supported. Issue an HMAC key on the storage account and pass "
            "`hmac_key_id` + `hmac_secret` instead."
        )
    parts: list[str] = ["TYPE gcs"]
    if "hmac_key_id" in credentials:
        parts.append(_secret_kv("KEY_ID", resolve_secret(credentials["hmac_key_id"])))
    if "hmac_secret" in credentials:
        parts.append(_secret_kv("SECRET", resolve_secret(credentials["hmac_secret"])))
    if "endpoint_url" in credentials:
        endpoint = resolve_secret(credentials["endpoint_url"])
        stripped = endpoint.split("://", 1)[-1].rstrip("/")
        parts.append(_secret_kv("ENDPOINT", stripped))
        parts.append("    URL_STYLE 'path'")
        if endpoint.startswith("http://"):
            parts.append("    USE_SSL false")
    body = ",\n".join(parts)
    return f"CREATE OR REPLACE SECRET {_sql_ident(secret_name)} (\n{body}\n)"


def _build_azure_secret_sql(credentials: dict, secret_name: str) -> str:
    """Azure Blob Storage secret. Field names follow dlt's `AzureCredentials`:
    `azure_storage_account_name` + `azure_storage_account_key`, or a
    `azure_storage_sas_token` for SAS auth.
    `connection_string` short-circuits ACCOUNT_NAME logic — required for
    Azurite (BlobEndpoint=http://127.0.0.1:10000/...)."""
    parts: list[str] = ["TYPE azure"]
    if "connection_string" in credentials:
        parts.append(_secret_kv("CONNECTION_STRING", resolve_secret(credentials["connection_string"])))
        body = ",\n".join(parts)
        return f"CREATE OR REPLACE SECRET {_sql_ident(secret_name)} (\n{body}\n)"
    account = credentials.get("azure_storage_account_name")
    key = credentials.get("azure_storage_account_key")
    sas = credentials.get("azure_storage_sas_token")
    if account:
        parts.append(_secret_kv("ACCOUNT_NAME", resolve_secret(account)))
        if key:
            parts.append(_secret_kv("ACCOUNT_KEY", resolve_secret(key)))
        elif sas:
            parts.append(_secret_kv("SAS_TOKEN", resolve_secret(sas)))
        else:
            raise ValueError(
                "azure connection: missing key. Provide `azure_storage_account_key` "
                "or `azure_storage_sas_token`."
            )
    else:
        raise ValueError(
            "azure connection: missing credentials. Provide "
            "`azure_storage_account_name` + `azure_storage_account_key` "
            "(or `azure_storage_sas_token`)."
        )
    body = ",\n".join(parts)
    return f"CREATE OR REPLACE SECRET {_sql_ident(secret_name)} (\n{body}\n)"


# ─── Object-store URI routing ────────────────────────────────────────────────
#
# The destination URI is the ground truth for *where* bytes land, so writers
# pick their extension + secret type from its scheme rather than from the
# linked Connection (which `_resolve()` drops before the writer sees it).
#
# `abfss://` is deliberately absent: DuckDB's azure extension rejects it under
# connection-string auth, which is the form Azurite requires.

_SCHEME_BACKEND: dict[str, str] = {
    "s3": "s3",
    "gcs": "gcs",
    "gs": "gcs",
    "az": "azure",
    "azure": "azure",
}

_BACKEND_EXTENSION: dict[str, str] = {
    "s3": "httpfs",
    "gcs": "httpfs",
    "azure": "azure",
}

_SECRET_BUILDER = {
    "s3": _build_s3_secret_sql,
    "gcs": _build_gcs_secret_sql,
    "azure": _build_azure_secret_sql,
}


def backend_for_uri(uri: str) -> str | None:
    """Return `s3` / `gcs` / `azure` for a remote URI, or None for local paths."""
    scheme, sep, _ = uri.partition("://")
    if not sep:
        return None
    return _SCHEME_BACKEND.get(scheme.lower())


def prepare_object_store(raw_con, uri: str, credentials: dict | None, secret_name: str) -> None:
    """Load the extension and register the SECRET needed to write `uri`.

    No-op for local filesystem paths. Raises when the URI carries a scheme we
    don't recognise, so a typo surfaces as an error instead of DuckDB trying
    to create a local file literally named `s3:/…`.
    """
    scheme, sep, _ = uri.partition("://")
    if not sep or scheme.lower() == "file":
        return
    backend = _SCHEME_BACKEND.get(scheme.lower())
    if backend is None:
        raise ValueError(
            f"destination URI '{uri}' uses unsupported scheme '{scheme}://'. "
            f"Supported: {', '.join(sorted(_SCHEME_BACKEND))} (or a local path)."
        )
    _ensure_ext(raw_con, _BACKEND_EXTENSION[backend])
    raw_con.execute(_SECRET_BUILDER[backend](credentials or {}, secret_name))
