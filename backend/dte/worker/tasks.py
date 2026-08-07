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
from dte.tenancy import tenant_context_var

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


async def _fetch_run_actual_tenant_id(run_id: str) -> str | None:
    """Look up a run row's *true* tenant_id, bypassing RLS.

    This is the one place a raw ``run_id`` off a job payload is trusted
    before its ``tenant_id`` claim is verified. Uses the ``SET LOCAL
    row_security = off`` escape hatch migration 016 documents for admin/ops
    queries — grep-detectable, and this is the reviewed use site for the
    job-queue worker.

    Returns None if no run with this id exists.
    """
    from sqlalchemy import text

    from dte.api.deps import _session_factory

    async with _session_factory()() as session:
        await session.execute(text("SET LOCAL row_security = off"))
        result = await session.execute(
            text("SELECT tenant_id FROM runs WHERE id = :id"), {"id": run_id}
        )
        row = result.mappings().fetchone()
        return row["tenant_id"] if row else None


def _default_stores() -> tuple[
    PipelineStore, RunStore, RunEventStore, SourceStore,
    DestinationStore, ConnectionStore, LookupTableStore,
]:
    from dte.api.deps import (
        get_connection_store,
        get_destination_store,
        get_lookup_table_store,
        get_pipeline_store,
        get_run_event_store,
        get_run_store,
        get_source_store,
    )

    return (
        get_pipeline_store(), get_run_store(), get_run_event_store(),
        get_source_store(), get_destination_store(), get_connection_store(),
        get_lookup_table_store(),
    )


async def execute_run_job(
    *,
    run_id: str,
    pipeline_id: str,
    tenant_id: str,
    p_store: PipelineStore | None = None,
    r_store: RunStore | None = None,
    re_store: RunEventStore | None = None,
    s_store: SourceStore | None = None,
    d_store: DestinationStore | None = None,
    c_store: ConnectionStore | None = None,
    lt_store: LookupTableStore | None = None,
    fetch_actual_tenant_id=None,
) -> None:
    """Job body for the procrastinate ``execute_run`` task (registered as a
    task in a later plan-046 step). Called with exactly the payload a
    worker process receives — plain strings, no live contextvar, no
    inherited asyncio context.

    Tenant rehydration is security-sensitive (plan 046, "Sharp edge 2"):
    the contextvar mechanism `dte.tenancy` documents does not cross a
    process boundary, so this rehydrates ``tenant_context_var`` from the
    payload **and cross-checks it against the run row's actual tenant_id**
    (fetched bypassing RLS via `_fetch_run_actual_tenant_id`) before any
    tenant-scoped store call. A mismatch — or a run id that no longer
    resolves at all — fails the run (under its *real* tenant, when known),
    logs at ERROR, and returns without executing anything.
    """
    lookup = fetch_actual_tenant_id or _fetch_run_actual_tenant_id
    actual_tenant_id = await lookup(run_id)

    if actual_tenant_id is None:
        _log.error(
            "worker: run row not found, refusing to execute",
            extra={"run_id": run_id, "pipeline_id": pipeline_id},
        )
        return

    stores = (p_store, r_store, re_store, s_store, d_store, c_store, lt_store)
    if any(s is None for s in stores):
        stores = _default_stores()
    p_store, r_store, re_store, s_store, d_store, c_store, lt_store = stores

    if actual_tenant_id != tenant_id:
        _log.error(
            "worker: tenant mismatch on job payload — refusing to execute",
            extra={
                "run_id": run_id,
                "pipeline_id": pipeline_id,
                "payload_tenant_id": tenant_id,
                "actual_tenant_id": actual_tenant_id,
            },
        )
        # Set the context to the *real* tenant (never the untrusted claim)
        # so the failure write itself passes RLS.
        token = tenant_context_var.set(actual_tenant_id)
        try:
            await r_store.update(
                run_id,
                status="failed",
                error="tenant mismatch: job payload does not match run tenant",
            )
        finally:
            tenant_context_var.reset(token)
        return

    token = tenant_context_var.set(actual_tenant_id)
    try:
        await _execute_pipeline(
            pipeline_id, run_id, p_store, r_store, re_store,
            s_store, d_store, c_store, lt_store,
        )
    finally:
        tenant_context_var.reset(token)
