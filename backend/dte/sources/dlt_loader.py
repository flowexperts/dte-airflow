from __future__ import annotations
import json
import os
from typing import Any, Callable

import dlt
import ibis

from dte.models.pipeline import DltSource


def resolve_secret(value: Any) -> Any:
    if isinstance(value, dict) and set(value.keys()) == {"env"}:
        return os.environ[value["env"]]
    return value


_JSONL_EXTS = (".jsonl", ".ndjson")
_JSON_EXTS = (".json",)
_CSV_EXTS = (".csv", ".tsv")
_PARQUET_EXTS = (".parquet", ".pq")


def _detect_format(path: str, explicit: str | None) -> str:
    """`config['format']` wins; otherwise decide by file extension.

    Returns one of: `json`, `jsonl`, `csv`, `parquet`.
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
    if lower.endswith(_JSON_EXTS):
        return "json"
    return "json"


def _sql_string_literal(s: str) -> str:
    """DuckDB SQL string literal — wrap in '', escape internal ' as ''."""
    return "'" + s.replace("'", "''") + "'"


def _sql_ident(name: str) -> str:
    """DuckDB identifier quote — wrap in "", escape internal " as ""."""
    return '"' + name.replace('"', '""') + '"'


def _duckdb_reader_call(paths: list[str], fmt: str) -> str:
    """SQL fragment: `read_<fmt>_auto([...])` — a table-valued function call."""
    path_list = "[" + ", ".join(_sql_string_literal(p) for p in paths) + "]"
    if fmt in ("json", "jsonl"):
        arg = "format='newline_delimited'" if fmt == "jsonl" else "format='auto'"
        return f"read_json_auto({path_list}, {arg})"
    if fmt == "csv":
        return f"read_csv_auto({path_list})"
    if fmt == "parquet":
        return f"read_parquet({path_list})"
    raise ValueError(f"unsupported filesystem format: {fmt!r}")


def _glob_local(bucket_url: str, file_glob: str) -> list[str]:
    """Expand `bucket_url + file_glob` to a sorted list of local paths."""
    from pathlib import Path
    import glob as _glob

    if bucket_url.startswith("file://"):
        root = bucket_url[len("file://"):]
    else:
        root = bucket_url
    pattern = str(Path(root) / file_glob)
    return sorted(_glob.glob(pattern, recursive=True))


def _load_from_fsspec(
    source: DltSource,
    con: ibis.BaseBackend,
    storage_options: dict,
) -> ibis.Table:
    raw_con = con.con
    config = source.config
    bucket_url = config["bucket_url"]
    file_glob = config.get("file_glob", "**/*.json")
    explicit_format = config.get("format")

    @dlt.resource(name=source.table)
    def _json_resource():
        import fsspec
        fs, _, _ = fsspec.get_fs_token_paths(
            bucket_url, storage_options=storage_options
        )
        matched = fs.glob(f"{bucket_url.rstrip('/')}/{file_glob}")
        if not matched:
            raise FileNotFoundError(
                f"No files matched '{file_glob}' in '{bucket_url}'"
            )
        for path in matched:
            fmt = _detect_format(path, explicit_format)
            with fs.open(path) as f:
                if fmt == "jsonl":
                    for line in f:
                        if isinstance(line, bytes):
                            line = line.decode("utf-8")
                        line = line.strip()
                        if not line:
                            continue
                        yield json.loads(line)
                else:
                    data = json.load(f)
                    if isinstance(data, list):
                        yield from data
                    else:
                        yield data

    pipeline = dlt.pipeline(
        pipeline_name=source.id,
        destination=dlt.destinations.duckdb(credentials=raw_con),
        dataset_name="dte_sources",
    )
    pipeline.run(_json_resource())
    return con.table(source.table, database=("memory", "dte_sources"))


def _load_filesystem(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    """Read local files directly via DuckDB's native readers.

    Nested JSON comes through as STRUCT columns (DuckDB default). The
    compiler's `_resolve_field` traverses dot-form refs (`order.amount`)
    into the struct; legacy `parent__child` refs still work because it
    falls back to `__`-joined lookups when struct traversal misses.
    """
    config = source.config
    bucket_url = config["bucket_url"]
    file_glob = config.get("file_glob", "**/*.json")
    explicit_format = config.get("format")

    matched = _glob_local(bucket_url, file_glob)
    if not matched:
        raise FileNotFoundError(
            f"No files matched '{file_glob}' in '{bucket_url}'"
        )

    fmt = _detect_format(matched[0], explicit_format)
    reader_sql = _duckdb_reader_call(matched, fmt)
    view_sql = (
        f"CREATE OR REPLACE VIEW {_sql_ident(source.table)} "
        f"AS SELECT * FROM {reader_sql}"
    )
    con.con.execute(view_sql)
    return con.table(source.table)


def _build_s3_storage_options(config: dict) -> dict:
    opts: dict = {}
    if "aws_access_key_id" in config:
        opts["key"] = resolve_secret(config["aws_access_key_id"])
    if "aws_secret_access_key" in config:
        opts["secret"] = resolve_secret(config["aws_secret_access_key"])
    if "aws_session_token" in config:
        opts["token"] = resolve_secret(config["aws_session_token"])
    if "region_name" in config:
        opts["client_kwargs"] = {"region_name": config["region_name"]}
    if "endpoint_url" in config:
        opts.setdefault("client_kwargs", {})["endpoint_url"] = config["endpoint_url"]
    return opts


def _load_s3(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    return _load_from_fsspec(source, con, _build_s3_storage_options(source.config))


def _build_gcs_storage_options(config: dict) -> dict:
    opts: dict = {}
    if "credentials_json" in config:
        creds = resolve_secret(config["credentials_json"])
        if isinstance(creds, str):
            creds = json.loads(creds)
        opts["token"] = creds
    return opts


def _load_gcs(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    return _load_from_fsspec(source, con, _build_gcs_storage_options(source.config))


def _load_sql_database(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    from dlt.sources.sql_database import sql_table

    raw_con = con.con
    config = source.config
    credentials = resolve_secret(config["credentials"])
    table_name = config["table"]
    schema = config.get("schema")

    resource = sql_table(
        credentials=credentials,
        table=table_name,
        schema=schema,
    ).with_name(source.table)

    pipeline = dlt.pipeline(
        pipeline_name=source.id,
        destination=dlt.destinations.duckdb(credentials=raw_con),
        dataset_name="dte_sources",
    )
    pipeline.run(resource)
    return con.table(source.table, database=("memory", "dte_sources"))


def _mongo_client(connection_url: str):
    from pymongo import MongoClient
    return MongoClient(connection_url)


def _load_mongodb(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    raw_con = con.con
    config = source.config
    connection_url = resolve_secret(config["connection_url"])
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


def _load_rest_api(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    from dlt.sources.rest_api import rest_api_source

    raw_con = con.con
    config = _resolve_rest_config(source.config)

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


def _resolve_rest_config(config: dict) -> dict:
    """Deep-copy the config and resolve any {"env": "..."} secrets inside
    client.auth / headers so callers can pass credentials via env vars."""
    import copy
    resolved = copy.deepcopy(config)
    client = resolved.get("client", {})
    if "auth" in client and isinstance(client["auth"], dict):
        for k, v in list(client["auth"].items()):
            client["auth"][k] = resolve_secret(v)
    if "headers" in client and isinstance(client["headers"], dict):
        for k, v in list(client["headers"].items()):
            client["headers"][k] = resolve_secret(v)
    return resolved


LOADERS: dict[str, Callable[[DltSource, ibis.BaseBackend], ibis.Table]] = {
    "filesystem": _load_filesystem,
    "s3": _load_s3,
    "gcs": _load_gcs,
    "sql_database": _load_sql_database,
    "mongodb": _load_mongodb,
    "rest_api": _load_rest_api,
}


def load_source(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    loader = LOADERS.get(source.source_type)
    if loader is None:
        raise NotImplementedError(
            f"source_type '{source.source_type}' is not supported"
        )
    return loader(source, con)
