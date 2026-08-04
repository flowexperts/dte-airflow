from __future__ import annotations

import ibis

from dte.engine.writers._copy import copy_to
from dte.models.pipeline import ParquetTarget


def write(
    table: ibis.Table,
    target: ParquetTarget,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
) -> dict:
    """Stream to a local path or object-store URI via DuckDB's native COPY.

    Replaces the old fsspec + `pyarrow.ParquetWriter` implementation: DuckDB
    reaches gcs/azure through the same secret machinery the readers use, so
    parquet is no longer S3-only and needs no `gcsfs`/`adlfs` dependency.
    """
    return copy_to(
        table, target.path, "FORMAT PARQUET", con=con, credentials=credentials
    )
