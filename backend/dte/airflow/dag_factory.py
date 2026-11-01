"""One DAG per DTE pipeline, built from its latest revision (plan 068).

Pipeline revision = DAG version: the revision id is a DAG tag, so every save
changes the serialized DAG and Airflow records a new DagVersion. The
pipeline's one schedule (if any, and enabled) is the DAG's cron.

Read from the `dte` schema at parse time. # ponytail: parse-time DB read;
if pipeline count makes dag-processor parsing slow, write DAG files on save.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlmodel import Session, select

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def build_dags() -> dict:
    from dte.airflow.assets import lineage
    from dte.airflow.db import sync_engine
    from dte.models.pipeline import Destination, PipelineRevision, Source

    R = PipelineRevision
    with Session(sync_engine()) as s:
        # Revisions cascade-delete with their pipeline, so this is "every pipeline".
        latest = list(s.exec(select(R).distinct(R.pipeline_id).order_by(R.pipeline_id, R.changed_at.desc())).all())
        sources = {x.id: x for x in s.exec(select(Source)).all()}
        dests = {x.id: x for x in s.exec(select(Destination)).all()}
        s.expunge_all()
    dags = (_dag_for(rev, *lineage(rev.config, sources, dests)) for rev in latest if _SAFE.match(rev.pipeline_id))
    return {d.dag_id: d for d in dags}


def _dag_for(rev, inlets=(), outlets=()):
    from airflow.sdk import DAG, Asset
    from airflow.timetables.trigger import CronTriggerTimetable

    from dte.airflow.notify import callbacks
    from dte.airflow.operators import DtePipelineOperator
    from dte.airflow.trigger import dag_id_for, revision_tag

    p, pid = rev.config, rev.pipeline_id
    sc = p.get("schedule") or {}
    cron = None
    if sc and sc.get("enabled", True):
        if sc.get("mode") == "assets":
            cron = [Asset(u) for u in sc["assets"]]
        else:
            cron = CronTriggerTimetable(sc["cron_expr"], timezone=sc.get("timezone", "UTC"))
    ptype = p.get("pipeline_type") or "transform"
    with DAG(
        dag_id=dag_id_for(pid), schedule=cron, start_date=datetime(2024, 1, 1), catchup=False,
        max_active_runs=16 if sc.get("overlap") == "allow" else 1,
        params=dict(sc.get("params") or {}),
        tags=["dte", f"dte-pipeline:{pid}", f"dte-type:{ptype}", revision_tag(rev.id)],
        dag_display_name=p.get("name") or pid,
        # A paused DAG queues manual runs forever. Per DAG, so an existing
        # Airflow needn't change its global default (plan 073).
        is_paused_upon_creation=False,
    ) as dag:
        # Manual and scheduled runs share this one task (plan 068), so retries
        # and notifications apply to both.
        DtePipelineOperator(
            task_id="run", pipeline_id=pid, revision_id=rev.id, eval_set_id=sc.get("eval_set_id"),
            retries=sc.get("retries", 0), retry_delay=timedelta(seconds=sc.get("retry_delay_s", 300)),
            execution_timeout=timedelta(seconds=sc["timeout_s"]) if sc.get("timeout_s") else None,
            inlets=[Asset(u) for u in inlets], outlets=[Asset(u) for u in outlets],
            **callbacks(p.get("notifications") or []),
        )
    return dag
