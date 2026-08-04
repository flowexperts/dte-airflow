from __future__ import annotations

import ibis

from dte.engine.writers._copy import copy_to
from dte.models.pipeline import ExcelTarget


def write(
    table: ibis.Table,
    target: ExcelTarget,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
) -> dict:
    """Write an ibis Table to `.xlsx` via DuckDB's `excel` extension.

    Routing through DuckDB keeps `openpyxl` / `xlsxwriter` out of the dep
    tree, and means xlsx reaches object stores on the same COPY path as
    every other format.
    """
    return copy_to(
        table,
        target.path,
        "FORMAT xlsx, HEADER true",
        con=con,
        credentials=credentials,
        extension="excel",
    )
