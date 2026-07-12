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


def _detect_format(path: str, explicit: str | None) -> str:
    """Explicit `format` config wins; otherwise decide by file extension."""
    if explicit:
        fmt = explicit.lower()
        if fmt in ("ndjson",):
            return "jsonl"
        return fmt
    lower = path.lower()
    if lower.endswith(".jsonl") or lower.endswith(".ndjson"):
        return "jsonl"
    return "json"


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
    return _load_from_fsspec(source, con, storage_options={})


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
