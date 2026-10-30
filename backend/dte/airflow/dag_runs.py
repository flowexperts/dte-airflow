"""Dag runs of DTE DAGs, read with Airflow's own session (plan 075).

api-server only: Airflow hides its metadata DB from DAG parsing and tasks.
Reading through Airflow (not DTE's engine) is what lets `DTE_DATABASE_URL`
point at a database that has no `dag_run` table.
"""
from __future__ import annotations

import asyncio

_COLS = ("run_id", "dag_id", "state", "queued_at", "start_date", "end_date", "run_type", "conf")


def _read(dag_ids: list[str] | None, run_id: str | None) -> list[dict]:
    from airflow.models.dagrun import DagRun
    from airflow.utils.session import create_session
    from sqlalchemy import select

    q = select(*(getattr(DagRun, c) for c in _COLS))
    q = q.where(DagRun.dag_id.in_(dag_ids)) if dag_ids is not None else q.where(DagRun.dag_id.like(r"dte\_\_%", escape="\\"))
    if run_id is not None:
        q = q.where(DagRun.run_id == run_id)
    with create_session() as s:
        rows = [dict(r._mapping) for r in s.execute(q)]
    for r in rows:  # DagRunState / DagRunType are str enums
        for c in ("state", "run_type"):
            r[c] = getattr(r[c], "value", r[c])
    return rows


async def dag_runs(dag_ids: list[str] | None = None, run_id: str | None = None) -> list[dict]:
    return await asyncio.to_thread(_read, dag_ids, run_id)
