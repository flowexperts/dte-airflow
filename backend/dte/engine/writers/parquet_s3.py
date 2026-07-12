from __future__ import annotations
import ibis
import fsspec
import pyarrow.parquet as pq
from dte.models.pipeline import ParquetS3Target


def write(table: ibis.Table, target: ParquetS3Target, con: ibis.BaseBackend | None = None) -> dict:
    arrow_table = table.to_pyarrow()
    with fsspec.open(target.bucket_url, "wb", **(target.storage_options or {})) as f:
        pq.write_table(arrow_table, f)
    return {"rows_written": arrow_table.num_rows, "location": target.bucket_url}
