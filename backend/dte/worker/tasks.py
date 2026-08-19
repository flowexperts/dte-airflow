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
import contextlib
import time
from datetime import UTC, datetime

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

# How often the worker touches runs.last_heartbeat_at while a distributed
# run is in flight (plan 046 task 8). dte.worker.reaper fails out any
# `running` run whose heartbeat has gone stale by more than 2x this —
# see that module's docstring for why a killed worker pod needs this
# rather than relying on queue-level retry.
HEARTBEAT_INTERVAL_SECONDS = 30


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
    *,
    es_store=None,
    ee_store=None,
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
                es_store=es_store, ee_store=ee_store,
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
            first_src = None
            if pipeline and pipeline.sources:
                from dte.models.pipeline import coerce_source_refs
                first_ref = coerce_source_refs(pipeline.sources)[0]
                first_src = await s_store.get(first_ref.source_id)
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
    es_store=None,
    ee_store=None,
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
    # Eval stores are deliberately *not* resolved here. Only an eval run
    # reads them, and constructing one requires DATABASE_URL — eagerly
    # building them would make every transform run depend on config it
    # never uses. `_run_eval_body` resolves them lazily instead.

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
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(run_id, r_store, interval_seconds=HEARTBEAT_INTERVAL_SECONDS)
    )
    try:
        await _execute_pipeline(
            pipeline_id, run_id, p_store, r_store, re_store,
            s_store, d_store, c_store, lt_store,
            es_store=es_store, ee_store=ee_store,
        )
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        tenant_context_var.reset(token)


async def _heartbeat_loop(
    run_id: str, r_store: RunStore, *, interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """Touch `runs.last_heartbeat_at` every `interval_seconds` for as long
    as this task lives. Runs alongside `_execute_pipeline` inside
    `execute_run_job`; cancelled in that call's `finally` block once the
    pipeline finishes (or raises). See `dte.worker.reaper` for the other
    half — failing out runs whose heartbeat goes stale.

    Ticks immediately (heartbeat-then-sleep, not sleep-then-heartbeat) so a
    run that dies within the first interval still leaves one heartbeat on
    record, distinguishing "started but the worker vanished almost
    immediately" from "never got a chance to touch the row at all" (the
    reaper's `started_at` fallback handles the latter).
    """
    while True:
        try:
            await r_store.update(run_id, last_heartbeat_at=datetime.now(UTC))
        except Exception:  # noqa — heartbeat failures must never crash the run
            _log.exception("heartbeat update failed", extra={"run_id": run_id})
        await asyncio.sleep(interval_seconds)


async def enqueue_run(
    pipeline_id: str,
    revision_id: str | None,
    *,
    tenant_id: str,
    schedule_id: str | None = None,
) -> tuple[str, int]:
    """Atomically insert the run row and enqueue its `execute_run` job.

    Shared by the API's flag-on trigger path (`dte.api.routes.pipelines.
    trigger_pipeline`, `tenant_id` from the request's tenant contextvar,
    `schedule_id=None`) and the ticker (`dte.worker.scheduler`, plan 047
    task 5 — `tenant_id` from the due schedule row since the ticker has no
    per-request tenant context, `schedule_id` set so the run row records
    "fired because it was 2am" per plan 047).

    True same-transaction atomicity needs both writes on the same
    connection/driver. dte's stores use asyncpg (via SQLAlchemy);
    procrastinate's async connector is psycopg (v3) — a different client
    library, so an ordinary SQLAlchemy transaction can't span both. Instead
    this borrows one connection from procrastinate's own psycopg pool,
    inserts the run row on it with plain SQL (same raw-SQL style
    `PostgresRunStore.create` uses), and defers the job on *that same
    connection* via `Task.configure(connection=...)` — procrastinate's
    documented mechanism for deferring inside a caller-managed transaction.
    One commit. Run row exists iff job exists, by construction.
    """
    import uuid as _uuid

    from dte.worker.app import EXECUTE_RUN_TASK_NAME, get_running_app

    app = await get_running_app()
    run_id = str(_uuid.uuid4())
    async with app.connector.pool.connection() as conn:
        async with conn.transaction():
            # RLS: `runs` has FORCE ROW LEVEL SECURITY with a USING policy
            # on tenant_id — the INSERT needs the session var set on *this*
            # connection, mirroring dte.store.postgres._open_tenant_session.
            await conn.execute(
                "SELECT set_config('dte.tenant_id', %s, true)", (tenant_id,)
            )
            await conn.execute(
                "INSERT INTO runs (id, pipeline_id, revision_id, status, tenant_id, schedule_id) "
                "VALUES (%s, %s, %s, 'pending', %s, %s)",
                (run_id, pipeline_id, revision_id, tenant_id, schedule_id),
            )
            job_id = await app.tasks[EXECUTE_RUN_TASK_NAME].configure(
                connection=conn,
            ).defer_async(run_id=run_id, pipeline_id=pipeline_id, tenant_id=tenant_id)
            await conn.execute(
                "UPDATE runs SET job_id = %s WHERE id = %s", (job_id, run_id)
            )
    return run_id, job_id
