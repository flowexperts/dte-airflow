from __future__ import annotations
import ibis
from dte.models.pipeline import CsvFileTarget


def write(table: ibis.Table, target: CsvFileTarget, con: ibis.BaseBackend | None = None) -> dict:
    df = table.execute()
    df.to_csv(target.path, index=False)
    return {"rows_written": len(df), "location": target.path}
