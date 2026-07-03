from __future__ import annotations
import json
import dlt
import ibis

from dte.models.pipeline import DltSource


def load_source(source: DltSource, con: ibis.BaseBackend) -> ibis.Table:
    raw_con = con.con

    if source.source_type == "filesystem":
        config = source.config
        bucket_url = config["bucket_url"]
        file_glob = config.get("file_glob", "**/*.json")

        from dlt.sources.filesystem import filesystem, read_jsonl

        @dlt.resource(name=source.table)
        def _json_resource():
            import fsspec
            fs, _, paths = fsspec.get_fs_token_paths(
                bucket_url, storage_options={}
            )
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

    raise NotImplementedError(f"source_type '{source.source_type}' is not supported")
