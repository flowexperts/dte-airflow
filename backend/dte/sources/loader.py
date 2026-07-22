from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import dlt
import ibis

from dte.models.pipeline import Source


def resolve_secret(value: Any) -> Any:
    if isinstance(value, dict) and set(value.keys()) == {"env"}:
        return os.environ[value["env"]]
    return value


_JSONL_EXTS = (".jsonl", ".ndjson")
_JSON_EXTS = (".json",)
_CSV_EXTS = (".csv", ".tsv")
_PARQUET_EXTS = (".parquet", ".pq")
_EXCEL_EXTS = (".xlsx",)


def _detect_format(path: str, explicit: str | None) -> str:
    """`config['format']` wins; otherwise decide by file extension.

    Returns one of: `json`, `jsonl`, `csv`, `parquet`, `excel`.
    """
    if explicit:
        fmt = explicit.lower()
        if fmt in ("ndjson",):
            return "jsonl"
        return fmt
    lower = path.lower()
    if lower.endswith(_JSONL_EXTS):
        return "jsonl"
    if lower.endswith(_CSV_EXTS):
        return "csv"
    if lower.endswith(_PARQUET_EXTS):
        return "parquet"
    if lower.endswith(_EXCEL_EXTS):
        return "excel"
    if lower.endswith(_JSON_EXTS):
        return "json"
    return "json"


def _sql_string_literal(s: str) -> str:
    """DuckDB SQL string literal — wrap in '', escape internal ' as ''."""
    return "'" + s.replace("'", "''") + "'"


def _sql_ident(name: str) -> str:
    """DuckDB identifier quote — wrap in "", escape internal " as ""."""
    return '"' + name.replace('"', '""') + '"'


def _ensure_format_ext(raw_con, fmt: str) -> None:
    """Some DuckDB reader TVFs live in extensions rather than core.
    Idempotently install + load the required extension for `fmt`."""
    if fmt == "excel":
        _ensure_ext(raw_con, "excel")


def _duckdb_reader_call(paths: list[str], fmt: str) -> str:
    """SQL fragment: `read_<fmt>_auto([...])` — a table-valued function call.

    Excel is a `UNION ALL` across `read_xlsx(...)` calls because
    `read_xlsx` doesn't accept a path list. Fine — xlsx sources rarely
    fan out to hundreds of files.
    """
    path_list = "[" + ", ".join(_sql_string_literal(p) for p in paths) + "]"
    if fmt in ("json", "jsonl"):
        arg = "format='newline_delimited'" if fmt == "jsonl" else "format='auto'"
        return f"read_json_auto({path_list}, {arg})"
    if fmt == "csv":
        return f"read_csv_auto({path_list})"
    if fmt == "parquet":
        return f"read_parquet({path_list})"
    if fmt == "excel":
        readers = [
            f"SELECT * FROM read_xlsx({_sql_string_literal(p)})" for p in paths
        ]
        return "(" + " UNION ALL BY NAME ".join(readers) + ")"
    raise ValueError(f"unsupported filesystem format: {fmt!r}")


def _glob_local(bucket_url: str, file_glob: str) -> list[str]:
    """Expand `bucket_url + file_glob` to a sorted list of local paths."""
    import glob as _glob
    from pathlib import Path

    if bucket_url.startswith("file://"):
        root = bucket_url[len("file://"):]
    else:
        root = bucket_url
    pattern = str(Path(root) / file_glob)
    return sorted(_glob.glob(pattern, recursive=True))


def _secret_kv(key: str, value: str) -> str:
    """Render one `KEY VALUE` line for a DuckDB CREATE SECRET body."""
    return f"    {key} {_sql_string_literal(value)}"


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
    is rejected; users must issue HMAC keys instead."""
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
    body = ",\n".join(parts)
    return f"CREATE OR REPLACE SECRET {_sql_ident(secret_name)} (\n{body}\n)"


def _build_azure_secret_sql(credentials: dict, secret_name: str) -> str:
    """Azure Blob Storage secret. Field names follow dlt's `AzureCredentials`:
    `azure_storage_account_name` + `azure_storage_account_key`, or a
    `azure_storage_sas_token` for SAS auth."""
    parts: list[str] = ["TYPE azure"]
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


def _load_remote_via_duckdb(
    source: Source,
    con: ibis.BaseBackend,
    extension: str,
    secret_sql: str,
) -> ibis.Table:
    """Install the required DuckDB extension, register a scoped SECRET, and
    materialise `bucket_url + file_glob` as a view over `read_*_auto`."""
    raw_con = con.con
    config = source.config
    bucket_url = config["bucket_url"].rstrip("/")
    file_glob = config.get("file_glob", "**/*.json")

    _ensure_ext(raw_con, extension)
    raw_con.execute(secret_sql)

    remote_pattern = f"{bucket_url}/{file_glob}"
    fmt = _detect_format(file_glob, source.format)
    _ensure_format_ext(raw_con, fmt)
    reader_sql = _duckdb_reader_call([remote_pattern], fmt)
    raw_con.execute(
        f"CREATE OR REPLACE VIEW {_sql_ident(source.table)} "
        f"AS SELECT * FROM {reader_sql}"
    )
    return con.table(source.table)


def _load_filesystem(source: Source, con: ibis.BaseBackend, credentials: dict) -> ibis.Table:
    """Read local files directly via DuckDB's native readers.

    Nested JSON comes through as STRUCT columns (DuckDB default). The
    compiler's `_resolve_field` traverses dot-form refs (`order.amount`)
    into the struct; legacy `parent__child` refs still work because it
    falls back to `__`-joined lookups when struct traversal misses.
    """
    config = source.config
    bucket_url = config["bucket_url"]
    file_glob = config.get("file_glob", "**/*.json")

    matched = _glob_local(bucket_url, file_glob)
    if not matched:
        raise FileNotFoundError(
            f"No files matched '{file_glob}' in '{bucket_url}'"
        )

    fmt = _detect_format(matched[0], source.format)
    _ensure_format_ext(con.con, fmt)
    reader_sql = _duckdb_reader_call(matched, fmt)
    view_sql = (
        f"CREATE OR REPLACE VIEW {_sql_ident(source.table)} "
        f"AS SELECT * FROM {reader_sql}"
    )
    con.con.execute(view_sql)
    return con.table(source.table)


def _load_s3(source: Source, con: ibis.BaseBackend, credentials: dict) -> ibis.Table:
    secret_name = f"dte_src_{source.id}_s3"
    return _load_remote_via_duckdb(
        source, con, "httpfs", _build_s3_secret_sql(credentials, secret_name)
    )


def _load_gcs(source: Source, con: ibis.BaseBackend, credentials: dict) -> ibis.Table:
    secret_name = f"dte_src_{source.id}_gcs"
    return _load_remote_via_duckdb(
        source, con, "httpfs", _build_gcs_secret_sql(credentials, secret_name)
    )


def _load_azure(source: Source, con: ibis.BaseBackend, credentials: dict) -> ibis.Table:
    secret_name = f"dte_src_{source.id}_azure"
    return _load_remote_via_duckdb(
        source, con, "azure", _build_azure_secret_sql(credentials, secret_name)
    )


_INSTALLED_EXTS: set[str] = set()


def _ensure_ext(raw_con, name: str) -> None:
    """Idempotently INSTALL + LOAD a DuckDB extension in this process."""
    if name not in _INSTALLED_EXTS:
        raw_con.execute(f"INSTALL {name}")
        _INSTALLED_EXTS.add(name)
    raw_con.execute(f"LOAD {name}")


def _sql_scanner_spec(credentials: str) -> tuple[str, str, str, str]:
    """(ext_name, attach_target, attach_type, default_schema) for a URL.

    - `sqlite:///path` → ('sqlite', 'path', 'sqlite', 'main')
    - `postgresql://…` → ('postgres', <url>, 'postgres', 'public')
    - `mysql://…`      → ('mysql', <url>, 'mysql', '')
    """
    if credentials.startswith("sqlite:///"):
        return "sqlite", credentials[len("sqlite:///"):], "sqlite", "main"
    if credentials.startswith(("postgresql://", "postgres://")):
        return "postgres", credentials, "postgres", "public"
    if credentials.startswith("mysql://"):
        return "mysql", credentials, "mysql", ""
    scheme = credentials.split("://", 1)[0] if "://" in credentials else credentials
    raise NotImplementedError(
        f"sql_database: unsupported credentials scheme '{scheme}://'. "
        "Supported: sqlite, postgresql, mysql."
    )


def _load_sql_database(source: Source, con: ibis.BaseBackend, credentials: dict) -> ibis.Table:
    """Attach the source via a DuckDB scanner extension and expose the
    requested table as a view. Queries stream through DuckDB — no dlt hop.

    `credentials["url"]` is the SQLAlchemy-style connection string."""
    raw_con = con.con
    config = source.config
    url = resolve_secret(credentials["url"])
    table_name = config["table"]
    user_schema = config.get("schema")

    ext, attach_target, attach_type, default_schema = _sql_scanner_spec(url)
    _ensure_ext(raw_con, ext)

    alias = f"dte_src_{source.id}"
    raw_con.execute(f"DETACH DATABASE IF EXISTS {_sql_ident(alias)}")
    raw_con.execute(
        f"ATTACH {_sql_string_literal(attach_target)} "
        f"AS {_sql_ident(alias)} (TYPE {attach_type}, READ_ONLY)"
    )

    schema = user_schema or default_schema
    qualified = (
        f"{_sql_ident(alias)}.{_sql_ident(schema)}.{_sql_ident(table_name)}"
        if schema
        else f"{_sql_ident(alias)}.{_sql_ident(table_name)}"
    )
    raw_con.execute(
        f"CREATE OR REPLACE VIEW {_sql_ident(source.table)} "
        f"AS SELECT * FROM {qualified}"
    )
    return con.table(source.table)


def _mongo_client(connection_url: str):
    from pymongo import MongoClient
    return MongoClient(connection_url)


def _load_mongodb(source: Source, con: ibis.BaseBackend, credentials: dict) -> ibis.Table:
    raw_con = con.con
    config = source.config
    connection_url = resolve_secret(credentials["url"])
    database = config["database"]
    collection = config["collection"]
    query_filter = config.get("filter", {})

    client = _mongo_client(connection_url)
    coll = client[database][collection]

    @dlt.resource(name=source.table)
    def _mongo_resource():
        for doc in coll.find(query_filter):
            doc.pop("_id", None)
            yield doc

    pipeline = dlt.pipeline(
        pipeline_name=source.id,
        destination=dlt.destinations.duckdb(credentials=raw_con),
        dataset_name="dte_sources",
    )
    pipeline.run(_mongo_resource())
    return con.table(source.table, database=("memory", "dte_sources"))


def _load_rest_api(source: Source, con: ibis.BaseBackend, credentials: dict) -> ibis.Table:
    from dlt.sources.rest_api import rest_api_source

    raw_con = con.con
    config = _merge_rest_credentials(source.config, credentials)

    src = rest_api_source(config)
    resources = list(src.resources.values())
    if not resources:
        raise ValueError("rest_api source produced no resources")
    resource = resources[0].with_name(source.table)

    pipeline = dlt.pipeline(
        pipeline_name=source.id,
        destination=dlt.destinations.duckdb(credentials=raw_con),
        dataset_name="dte_sources",
    )
    pipeline.run(resource)
    return con.table(source.table, database=("memory", "dte_sources"))


def _merge_rest_credentials(config: dict, credentials: dict) -> dict:
    """Return a fresh rest_api config with `client.auth` and `client.headers`
    merged from the linked Connection's credentials. Values are still
    passed through `resolve_secret()` for `{env: X}` back-compat."""
    import copy
    resolved = copy.deepcopy(config)
    client = resolved.setdefault("client", {})
    for key in ("auth", "headers"):
        if key in credentials and isinstance(credentials[key], dict):
            merged = dict(client.get(key) or {})
            for k, v in credentials[key].items():
                merged[k] = resolve_secret(v)
            client[key] = merged
    return resolved


LOADERS: dict[str, Callable[[Source, ibis.BaseBackend, dict], ibis.Table]] = {
    "filesystem": _load_filesystem,
    "s3": _load_s3,
    "gcs": _load_gcs,
    "azure": _load_azure,
    "sql_database": _load_sql_database,
    "mongodb": _load_mongodb,
    "rest_api": _load_rest_api,
}


def load_source(source: Source, con: ibis.BaseBackend, credentials: dict) -> ibis.Table:
    """`credentials` is the linked Connection's decrypted credentials
    dict — always a dict, empty for `local_fs`."""
    loader = LOADERS.get(source.source_type)
    if loader is None:
        raise NotImplementedError(
            f"source_type '{source.source_type}' is not supported"
        )
    return loader(source, con, credentials)
