from __future__ import annotations

import fsspec
import ibis
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
    """Stream Arrow record batches into Parquet.

    Previous implementation buffered the whole result set via `to_pyarrow()`.
    Now: `to_pyarrow_batches()` iterates without holding it all at once, and
    `ParquetWriter.write_batch` flushes each batch to the fsspec-backed sink.
    """
    storage_options = _fsspec_storage_options(credentials or {})
    batches = table.to_pyarrow_batches()
    # Peek the first batch to learn the schema; ParquetWriter needs it up front.
    try:
        first = next(iter(batches))
    except StopIteration:
        # Empty result — write an empty file so `location` still points at
        # something readable.
        first = None
    rows = 0
    with fsspec.open(target.bucket_url, "wb", **storage_options) as f:
        if first is None:
            # No batches → write a zero-row Parquet with just the schema.
            empty_schema = table.schema().to_pyarrow()
            with pq.ParquetWriter(f, empty_schema):
                pass
        else:
            with pq.ParquetWriter(f, first.schema) as w:
                w.write_batch(first)
                rows += first.num_rows
                for batch in batches:
                    w.write_batch(batch)
                    rows += batch.num_rows
    return {"rows_written": rows, "location": target.bucket_url}
