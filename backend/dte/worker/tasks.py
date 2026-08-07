"""Run execution — the job boundary for plan 046.

`_execute_pipeline` moved here verbatim from `dte.api.routes.pipelines`
(plan 046 task 3). It is the function both the flag-off `asyncio.create_task`
dispatch path (`trigger_pipeline` in `dte/api/routes/pipelines.py`) and the
flag-on procrastinate job (`execute_run`, added in a later task) call.

`_run_body` stays in `dte.api.routes.pipelines`, unchanged — it already
took only serialisable arguments (`pipeline_id`, `run_id`, store instances),
making it a natural job boundary without needing to touch its body.
"""
from __future__ import annotations

import asyncio
import time

from dte import metrics
from dte.api.routes.pipelines import _run_body
from dte.config import get_settings
from dte.logging import decrypt_context_var, get_logger, run_id_var
from dte.store.base import (
    ConnectionStore,
    DestinationStore,
    LookupTableStore,
    PipelineStore,
    RunEventStore,
    RunStore,
    SourceStore,
)

_log = get_logger("dte.worker.tasks")


async def _execute_pipeline(
    pipeline_id: str,
    run_id: str,
    p_store: PipelineStore,
    r_store: RunStore,
    re_store: RunEventStore,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
    lt_store: LookupTableStore,
):
    settings = get_settings()
    token = run_id_var.set(run_id)
    decrypt_context_var.set("pipeline_run")
    await r_store.update(run_id, status="running")
    _log.info("run started", extra={"pipeline_id": pipeline_id})
    metrics.active_runs.inc()
    started = time.monotonic()
    final_status = "failed"  # pessimistic default; success path sets "completed"
    try:
        await asyncio.wait_for(
            _run_body(
                pipeline_id, run_id, p_store, r_store, re_store,
                s_store, d_store, c_store, lt_store,
            ),
            timeout=settings.run_timeout_seconds,
        )
        final_status = "completed"
    except TimeoutError:
        _log.warning("run timed out", extra={"pipeline_id": pipeline_id})
        await r_store.update(
            run_id,
            status="failed",
            error=f"run exceeded timeout of {settings.run_timeout_seconds}s",
        )
    except asyncio.CancelledError:
        _log.info("run cancelled", extra={"pipeline_id": pipeline_id})
        await r_store.update(run_id, status="failed", error="cancelled")
        final_status = "cancelled"
    except Exception as e:
        _log.exception("run failed", extra={"pipeline_id": pipeline_id})
        await r_store.update(run_id, status="failed", error=str(e))
    finally:
        run_id_var.reset(token)
        metrics.active_runs.dec()
        metrics.pipeline_runs_total.labels(status=final_status).inc()
        # Best-effort source_type label: pick the pipeline's first source kind.
        # Multi-source runs still surface via HTTP RED metrics on trigger.
        try:
            pipeline = await p_store.get(pipeline_id)
            first_src = await s_store.get(pipeline.sources[0]) if pipeline and pipeline.sources else None
            src_type = first_src.source_type if first_src else "unknown"
        except Exception:  # noqa — metric emission must never mask a run error
            src_type = "unknown"
        metrics.pipeline_run_duration_seconds.labels(source_type=src_type).observe(
            time.monotonic() - started
        )
