"""Upsert a `dte.run_results` row (keyed by Airflow dag run id)."""
from __future__ import annotations

import json

from sqlalchemy import text

_JSONB = ("params", "quality_checks", "sql_query", "scores", "events")
_COLS = ("dag_id", "pipeline_id", "revision_id", "status", "error", "rows_written", "location",
         "params", "quality_checks", "sql_query", "scores", "eval_set_id", "labels_version",
         "config_digest", "sweep_id", "events")


def record_result(engine, run_id: str, **fields) -> None:
    cols = [c for c in _COLS if c in fields]
    vals = ", ".join(f"CAST(:{c} AS jsonb)" if c in _JSONB else f":{c}" for c in cols)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("dag_id", "pipeline_id"))
    binds = {c: json.dumps(fields[c], default=str) if c in _JSONB and fields[c] is not None else fields[c] for c in cols}
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO run_results (run_id, {', '.join(cols)}) VALUES (:run_id, {vals}) "
                 f"ON CONFLICT (run_id) DO UPDATE SET {sets}"),
            {"run_id": run_id, **binds},
        )


def eval_history(engine, eval_set_id: str, limit: int = 50) -> list[dict]:
    """Scored runs of one eval set, newest first: what the regression check
    compares against. `run_results` alone, so tasks never read `dag_run`."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT run_id AS id, config_digest, labels_version, scores FROM run_results "
                 "WHERE eval_set_id = :e AND scores IS NOT NULL ORDER BY created_at DESC LIMIT :n"),
            {"e": eval_set_id, "n": limit},
        )
        return [dict(r) for r in rows.mappings()]
