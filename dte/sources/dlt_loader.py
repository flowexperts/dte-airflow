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


def _load_filesystem(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    raw_con = con.con
    config = source.config
    bucket_url = config["bucket_url"]
    file_glob = config.get("file_glob", "**/*.json")

    @dlt.resource(name=source.table)
    def _json_resource():
        import fsspec
        fs, _, _ = fsspec.get_fs_token_paths(bucket_url, storage_options={})
        matched = fs.glob(f"{bucket_url.rstrip('/')}/{file_glob}")
        if not matched:
            raise FileNotFoundError(
                f"No files matched '{file_glob}' in '{bucket_url}'"
            )
        for path in matched:
            with fs.open(path) as f:
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


LOADERS: dict[str, Callable[[DltSource, ibis.BaseBackend], ibis.Table]] = {
    "filesystem": _load_filesystem,
}


def load_source(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    loader = LOADERS.get(source.source_type)
    if loader is None:
        raise NotImplementedError(
            f"source_type '{source.source_type}' is not supported"
        )
    return loader(source, con)
