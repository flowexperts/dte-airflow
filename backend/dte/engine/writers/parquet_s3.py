from __future__ import annotations
import ibis
import fsspec
import pyarrow.parquet as pq
from dte.models.pipeline import ParquetS3Target


def _fsspec_storage_options(credentials: dict) -> dict:
    """Map dte-style s3 credentials (as stored on the Connection) into
    fsspec/s3fs kwargs."""
    mapping = {
        "aws_access_key_id": "key",
        "aws_secret_access_key": "secret",
        "aws_session_token": "token",
        "endpoint_url": "endpoint_url",
        "region_name": "region_name",
    }
    return {mapping[k]: v for k, v in credentials.items() if k in mapping}


def write(
    table: ibis.Table,
    target: ParquetS3Target,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
) -> dict:
    arrow_table = table.to_pyarrow()
    storage_options = _fsspec_storage_options(credentials or {})
    with fsspec.open(target.bucket_url, "wb", **storage_options) as f:
        pq.write_table(arrow_table, f)
    return {"rows_written": arrow_table.num_rows, "location": target.bucket_url}
