"""DtePipelineOperator: run one DTE pipeline (transform, quality or eval)."""
from __future__ import annotations

from datetime import UTC, datetime
from functools import partial

from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.sdk import BaseOperator
from sqlmodel import Session, select

from dte.airflow.connections import to_dte
from dte.airflow.db import sync_engine
from dte.airflow.results import eval_history, record_result
from dte.airflow.runner import run_pipeline
from dte.store.files import file_revision


def run_as_of(context, config: dict):
    """A scheduled run's logical date in its schedule's timezone, so a retry or
    rerun resolves `{{today}}` to the same day (plan 070). Manual runs have no
    logical date: None, i.e. now."""
    ld = context.get("logical_date")
    if ld is None:
        return None
    return ld.in_timezone((config.get("schedule") or {}).get("timezone", "UTC"))


def record_event(events: list[dict], idx, op, status, msg=None) -> None:
    """One row per step (or run phase, idx=None keyed by its title in `op`):
    "started" is updated in place by its terminal event."""
    now = datetime.now(UTC).isoformat()
    done = status in ("completed", "failed", "skipped")
    ev = next((e for e in events if e["step_index"] == idx and e["op"] == op), None)
    if ev is None:
        events.append({"step_index": idx, "op": op, "status": status, "message": msg,
                       "started_at": now, "finished_at": now if done else None})
    else:
        ev.update(status=status, message=msg, finished_at=now if done else ev["finished_at"])


class DtePipelineOperator(BaseOperator):
    """Runs one pipeline revision: the one the dag run's conf pins (manual
    runs), else the one this DAG version was built from (scheduled runs).
    Resolves each source and the destination through Airflow Connections,
    records a `run_results` row, and fails the task on a `fail`-severity
    quality check."""

    def __init__(self, *, pipeline_id: str, revision_id: str | None = None,
                 eval_set_id: str | None = None, **kw):
        super().__init__(**kw)
        self.pipeline_id = pipeline_id
        self.revision_id = revision_id
        self.eval_set_id = eval_set_id

    @staticmethod
    def _regression(engine, eval_set_id, res, run_id):
        """Best effort: a failed comparison must never fail the run."""
        from dte.evals.regression import detect_eval_regression

        try:
            return detect_eval_regression(eval_history(engine, eval_set_id, limit=50), res.config_digest,
                                          res.labels_version, run_id, res.scores)
        except Exception:
            return None

    def execute(self, context):
        from dte.models.eval import EvalExample, EvalSet
        from dte.models.pipeline import (
            Destination,
            LookupTable,
            Pipeline,
            PipelineRevision,
            Source,
            coerce_source_refs,
        )

        conf = (context["dag_run"].conf or {}) if context.get("dag_run") else {}
        run_id, dag_id = context["run_id"], context["dag"].dag_id
        eval_set_id = conf.get("eval_set_id") or self.eval_set_id
        engine = sync_engine()
        events: list[dict] = []

        on_event = partial(record_event, events)

        # Manual runs carry params in conf; scheduled runs carry them as DAG params.
        user_params = conf.get("params")
        if user_params is None:
            user_params = dict(context.get("params") or {})
        revision_id = conf.get("revision_id") or self.revision_id
        base = dict(dag_id=dag_id, pipeline_id=self.pipeline_id, revision_id=revision_id,
                    sweep_id=conf.get("sweep_id"), eval_set_id=eval_set_id, params=conf.get("context"))
        record_result(engine, run_id, status="running", **base)
        try:
            with Session(engine) as s:
                # File mode (plan 090): the revision is the file's content hash.
                rev = file_revision(self.pipeline_id, revision_id) or (
                    s.get(PipelineRevision, revision_id) if revision_id else None)
                if rev is None or rev.pipeline_id != self.pipeline_id:
                    raise AirflowFailException(f"revision {revision_id!r} of pipeline {self.pipeline_id} not found")
                pipeline = Pipeline(**rev.config)
                sources = []
                for ref in coerce_source_refs(pipeline.sources):
                    src = s.get(Source, ref.source_id)
                    if src is None:
                        raise AirflowFailException(f"source not found: {ref.source_id}")
                    conn, creds = to_dte(src.connection_id)
                    sources.append((ref, src, conn, creds))
                destination = None
                if (pipeline.pipeline_type or "transform") == "transform":
                    dest = s.get(Destination, pipeline.output_id)
                    if dest is None:
                        raise AirflowFailException(f"destination not found: {pipeline.output_id}")
                    dest.narrow_config()
                    destination = (dest, to_dte(dest.connection_id)[1])
                lookups = {}
                for step in pipeline.steps or []:
                    if step.get("op") == "map" and step.get("mode") == "lookup" and step.get("lookup_id"):
                        lookups[step["lookup_id"]] = s.get(LookupTable, step["lookup_id"])
                eval_set = examples = None
                if pipeline.pipeline_type == "eval":
                    eval_set = s.get(EvalSet, eval_set_id) if eval_set_id else None
                    if eval_set is None:
                        raise AirflowFailException("eval pipeline needs an eval_set_id (DAG run conf or schedule)")
                    examples = list(s.exec(select(EvalExample).where(EvalExample.eval_set_id == eval_set_id)).all())
                s.expunge_all()

            from dte.compiler.interpolate import resolve_context
            values = conf.get("context") or resolve_context(
                pipeline, user_params or None, as_of=run_as_of(context, rev.config))
            res = run_pipeline(pipeline, sources, destination, values, on_event,
                               lookups=lookups, run_id=run_id, eval_set=eval_set, eval_examples=examples,
                               log=self.log)
            if res.scores:
                res.scores["regression"] = self._regression(engine, eval_set_id, res, run_id)
                if not res.scores["regression"]:
                    del res.scores["regression"]
                else:
                    res.status = "completed_with_warnings"
        except AirflowFailException as e:
            record_result(engine, run_id, status="failed", error=str(e), events=events, **base)
            raise
        except Exception as e:
            record_result(engine, run_id, status="failed", error=f"{type(e).__name__}: {e}", events=events, **base)
            raise

        record_result(
            engine, run_id, status=res.status, rows_written=res.rows_written, location=res.location,
            quality_checks=res.quality, sql_query=res.sql_query, scores=res.scores,
            labels_version=res.labels_version, config_digest=res.config_digest, events=events, **base,
        )
        summary = {"rows_written": res.rows_written, "status": res.status,
                   "quality": {"failed": sum(1 for q in res.quality if not q["passed"] and q["severity"] == "fail"),
                               "warned": sum(1 for q in res.quality if not q["passed"] and q["severity"] == "warn")}}
        if res.scores:
            summary["scores"] = {k: v for k, v in res.scores.items() if isinstance(v, (int, float))}
        if res.status == "failed_quality":
            raise AirflowFailException(f"quality checks failed: {summary['quality']}")
        if res.skip_reason:
            # Skipped, not succeeded: no alert, and no Asset event wakes downstream pipelines.
            raise AirflowSkipException(res.skip_reason)
        return summary
