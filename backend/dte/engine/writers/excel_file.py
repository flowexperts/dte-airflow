from __future__ import annotations
import ibis
from dte.models.pipeline import ExcelFileTarget


def write(
    table: ibis.Table, target: ExcelFileTarget, con: ibis.BaseBackend | None = None
) -> dict:
    """Write an ibis Table to `.xlsx` via DuckDB's `excel` extension.

    Routing through DuckDB keeps `openpyxl` / `xlsxwriter` out of the
    dep tree. The extension's `COPY … TO … (FORMAT xlsx)` accepts any
    subquery, so we ask the table's own backend to run it.
    """
    backend = con if con is not None else table._find_backend()
    raw = backend.con
    raw.execute("INSTALL excel")
    raw.execute("LOAD excel")

    view_name = "_dte_excel_out"
    backend.create_view(view_name, table, overwrite=True)
    quoted_path = target.path.replace("'", "''")
    raw.execute(
        f"COPY (SELECT * FROM {view_name}) TO '{quoted_path}' "
        f"(FORMAT xlsx, HEADER true)"
    )

    (rows,) = raw.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()
    return {"rows_written": int(rows), "location": target.path}
