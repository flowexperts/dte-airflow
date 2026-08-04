from __future__ import annotations

import ibis

from dte.engine.writers._copy import copy_to
from dte.models.pipeline import CsvTarget


def write(
    table: ibis.Table,
    target: CsvTarget,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
) -> dict:
    """Stream to a local path or object-store URI via DuckDB's native COPY."""
    return copy_to(
        table, target.path, "FORMAT CSV, HEADER", con=con, credentials=credentials
    )
