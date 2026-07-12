from __future__ import annotations
import json
from pathlib import Path
import ibis
from dte.models.pipeline import JsonFileTarget


def write(table: ibis.Table, target: JsonFileTarget, con: ibis.BaseBackend | None = None) -> dict:
    df = table.execute()
    records = df.to_dict(orient="records")
    Path(target.path).write_text(json.dumps(records, default=str, indent=2))
    return {"rows_written": len(records), "location": target.path}
