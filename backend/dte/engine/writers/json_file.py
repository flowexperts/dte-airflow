from __future__ import annotations

import ibis

from dte.engine.writers._copy import copy_to
from dte.models.pipeline import JsonTarget


def write(
    table: ibis.Table,
    target: JsonTarget,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
) -> dict:
    """Stream to a local path or object-store URI via DuckDB's native COPY.

    `ARRAY true` preserves the JSON array shape that `runs/{id}/output` and
    the frontend `RunOutputPreview` expect — do not switch this to
    newline-delimited without updating both.
    """
    return copy_to(
        table, target.path, "FORMAT JSON, ARRAY true", con=con, credentials=credentials
    )
