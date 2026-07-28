from __future__ import annotations

import asyncio
import contextvars
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from dte import runs as run_registry
from dte.api.deps import (
    get_connection_store,
    get_current_user,
    get_destination_store,
    get_lookup_table_store,
    get_pipeline_revision_store,
    get_pipeline_store,
    get_run_event_store,
    get_run_store,
    get_source_store,
)
from dte.compiler.ibis_compiler import compile_pipeline
from dte.pipelines.diff import diff_pipeline, summarise_diff
from dte.config import get_settings
from dte import metrics
from dte.engine.duckdb_engine import DuckDBEngine  # noqa: F401 — still used as type hint fallback
from dte.engine.registry import get_engine
from dte.logging import decrypt_context_var, get_logger, run_id_var
from dte.engine.backend_registry import BackendRegistry
from dte.models.pipeline import (
    Connection,
    Destination,
    LookupTable,
    Pipeline,
    PipelineBase,
    PipelineRevisionBase,
    Source,
)
from dte.models.user import User
from dte.security.permissions import requires
from dte.sources.loader import load_source
from dte.store.base import (
    ConnectionStore,
    DestinationStore,
    LookupTableStore,
    PipelineRevisionStore,
    PipelineStore,
    RunEventStore,
    RunStore,
    SourceStore,
)
from dte.tracing import tracer

router = APIRouter()
_log = get_logger("dte.pipelines")


async def _record_revision(
    pipeline: PipelineBase,
    rev_store: PipelineRevisionStore,
    user: User | None,
) -> str:
    """Persist an immutable snapshot of the pipeline after every accepted
    POST/PUT. Returns the new revision id. Populates `summary` from the
    diff against the prior revision (None for the first revision)."""
    import uuid as _uuid
    new_config = pipeline.model_dump()
    prior = await rev_store.latest_for_pipeline(pipeline.id)
    summary: str | None = None
    if prior is not None:
        summary = summarise_diff(diff_pipeline(prior.config, new_config))
    rev = PipelineRevisionBase(
        id=str(_uuid.uuid4()),
        pipeline_id=pipeline.id,
        config=new_config,
        changed_by=user.id if user else None,
        summary=summary,
    )
    await rev_store.save(rev)
    return rev.id


async def _validate_pipeline_refs(
    pipeline: PipelineBase,
    s_store: SourceStore,
    d_store: DestinationStore,
):
    """Raise 422 if any source id or the destination id doesn't exist."""
    missing_sources = []
    for sid in pipeline.sources:
        if not await s_store.get(sid):
            missing_sources.append(sid)
    missing_dest = None if await d_store.get(pipeline.output_id) else pipeline.output_id
    if missing_sources or missing_dest:
        detail: dict = {}
        if missing_sources:
            detail["missing_sources"] = missing_sources
        if missing_dest:
            detail["missing_destination"] = missing_dest
        raise HTTPException(status_code=422, detail=detail)


async def _validate_engine_compat(
    pipeline: PipelineBase,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
) -> str:
    """Resolve pipeline.engine (handling "auto") and reject 422 if the
    engine can't read every source or write the destination.

    Returns the resolved engine name so callers can pass it forward to
    ``get_engine`` without re-computing.  Assumes _validate_pipeline_refs
    has already verified source/destination ids exist.
    """
    from dte.engine.registry import trino_enabled
    from dte.models.pipeline import (
        EngineIncompatible,
        resolve_pipeline_engine,
        validate_pipeline_engine_compat,
    )

    src_types: list[tuple[str, str]] = []
    for sid in pipeline.sources:
        source = await s_store.get(sid)
        if not source:
            continue  # already caught by _validate_pipeline_refs
        conn = await c_store.get(source.connection_id)
        if not conn:
            raise HTTPException(
                status_code=422,
                detail=f"Source '{sid}' references missing connection '{source.connection_id}'",
            )
        src_types.append((sid, conn.connection_type))

    destination = await d_store.get(pipeline.output_id)
    if not destination:
        raise HTTPException(status_code=422, detail=f"Destination not found: {pipeline.output_id}")
    dest_conn = await c_store.get(destination.connection_id)
    if not dest_conn:
        raise HTTPException(
            status_code=422,
            detail=f"Destination '{destination.id}' references missing connection '{destination.connection_id}'",
        )

    engine_choice = getattr(pipeline, "engine", None) or "auto"
    resolved = resolve_pipeline_engine(engine_choice, [ct for _, ct in src_types])

    if resolved == "trino" and not trino_enabled():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "trino_not_enabled",
                "engine": "trino",
                "message": (
                    "Trino engine is not enabled on this deployment. "
                    "Set DTE_TRINO_ENABLED=true and configure DTE_TRINO_* env "
                    "vars, or choose a different engine."
                ),
            },
        )

    try:
        validate_pipeline_engine_compat(
            engine=resolved,
            sources=src_types,  # type: ignore[arg-type]
            destination=(destination.id, dest_conn.connection_type),
        )
    except EngineIncompatible as e:
        raise HTTPException(status_code=422, detail=e.payload()) from e

    return resolved


@router.post("/pipelines", dependencies=[Depends(requires("pipeline:write"))])
async def create_pipeline(
    pipeline: PipelineBase,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
    user: User = Depends(get_current_user),
):
    await _validate_pipeline_refs(pipeline, s_store, d_store)
    await _validate_engine_compat(pipeline, s_store, d_store, c_store)
    await store.save(Pipeline(**pipeline.model_dump()))
    await _record_revision(pipeline, rev_store, user)
    return {"id": pipeline.id}


@router.get("/pipelines", dependencies=[Depends(requires("pipeline:read"))])
async def list_pipelines(limit: int = 50, offset: int = 0, store: PipelineStore = Depends(get_pipeline_store)) -> list[Pipeline]:
    return await store.list(limit=limit, offset=offset)


@router.get("/pipelines/{pipeline_id}", dependencies=[Depends(requires("pipeline:read"))])
async def get_pipeline(pipeline_id: str, store: PipelineStore = Depends(get_pipeline_store)) -> Pipeline:
    p = await store.get(pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return p


@router.put("/pipelines/{pipeline_id}", dependencies=[Depends(requires("pipeline:write"))])
async def update_pipeline(
    pipeline_id: str,
    pipeline: PipelineBase,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
    user: User = Depends(get_current_user),
) -> Pipeline:
    if pipeline.id != pipeline_id:
        raise HTTPException(status_code=400, detail="Pipeline id in path and body must match")
    existing = await store.get(pipeline_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await _validate_pipeline_refs(pipeline, s_store, d_store)
    await _validate_engine_compat(pipeline, s_store, d_store, c_store)
    row = Pipeline(**pipeline.model_dump())
    await store.save(row)
    await _record_revision(pipeline, rev_store, user)
    return row


@router.delete("/pipelines/{pipeline_id}", status_code=204, dependencies=[Depends(requires("pipeline:delete"))])
async def delete_pipeline(
    pipeline_id: str,
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
):
    existing = await p_store.get(pipeline_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await r_store.delete_for_pipeline(pipeline_id)
    await p_store.delete(pipeline_id)
    return Response(status_code=204)


@router.get(
    "/pipelines/{pipeline_id}/revisions",
    dependencies=[Depends(requires("pipeline:read"))],
)
async def list_pipeline_revisions(
    pipeline_id: str,
    limit: int = 100,
    p_store: PipelineStore = Depends(get_pipeline_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
):
    if not await p_store.get(pipeline_id):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return await rev_store.list_for_pipeline(pipeline_id, limit=limit)


@router.get(
    "/pipelines/{pipeline_id}/revisions/{revision_id}",
    dependencies=[Depends(requires("pipeline:read"))],
)
async def get_pipeline_revision(
    pipeline_id: str,
    revision_id: str,
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
):
    rev = await rev_store.get(revision_id)
    if rev is None or rev.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail="Revision not found")
    return rev


@router.get(
    "/pipelines/{pipeline_id}/diff",
    dependencies=[Depends(requires("pipeline:read"))],
)
async def diff_pipeline_revisions(
    pipeline_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
):
    a = await rev_store.get(from_)
    b = await rev_store.get(to)
    if a is None or a.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail=f"Revision not found: {from_}")
    if b is None or b.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail=f"Revision not found: {to}")
    diff = diff_pipeline(a.config, b.config)
    return {
        "from": {"id": a.id, "changed_at": a.changed_at, "changed_by": a.changed_by},
        "to": {"id": b.id, "changed_at": b.changed_at, "changed_by": b.changed_by},
        "diff": diff,
        "summary": summarise_diff(diff),
    }


async def _resolve_lookups(
    pipeline: Pipeline,
    lt_store: LookupTableStore,
) -> dict[str, LookupTable]:
    """Collect every lookup_id referenced by map/lookup steps and fetch the
    corresponding LookupTable rows. Missing rows → 422 naming what's gone."""
    ids: set[str] = set()
    for step in pipeline.steps or []:
        if step.get("op") == "map" and step.get("mode") == "lookup":
            lid = step.get("lookup_id")
            if lid:
                ids.add(lid)
    resolved: dict[str, LookupTable] = {}
    missing: list[str] = []
    for lid in ids:
        lt = await lt_store.get(lid)
        if lt is None:
            missing.append(lid)
        else:
            resolved[lid] = lt
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"missing_lookup_tables": sorted(missing)},
        )
    return resolved


async def _resolve(
    pipeline: Pipeline,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
) -> tuple[list[tuple[Source, "Connection", dict]], tuple[Destination, dict]]:
    """Resolve pipeline id refs to (Source, Connection, credentials) tuples
    and (Destination, credentials). Missing anything → 422 naming what's gone."""
    sources: list[tuple[Source, "Connection", dict]] = []
    for sid in pipeline.sources:
        source = await s_store.get(sid)
        if not source:
            raise HTTPException(status_code=422, detail=f"Source not found: {sid}")
        conn = await c_store.get(source.connection_id)
        if not conn:
            raise HTTPException(
                status_code=422,
                detail=f"Source '{sid}' references missing connection '{source.connection_id}'",
            )
        sources.append((source, conn, conn.credentials))

    destination = await d_store.get(pipeline.output_id)
    if not destination:
        raise HTTPException(status_code=422, detail=f"Destination not found: {pipeline.output_id}")
    dest_conn = await c_store.get(destination.connection_id)
    if not dest_conn:
        raise HTTPException(
            status_code=422,
            detail=f"Destination '{destination.id}' references missing connection '{destination.connection_id}'",
        )
    return sources, (destination, dest_conn.credentials)


async def _compile_body_pipeline(
    body: PipelineBase,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
    lt_store: LookupTableStore,
    *,
    on_step_schema=None,
):
    """Shared plumbing for endpoints that compile an unsaved pipeline body.

    Resolves source/destination/connection/lookup refs from the given
    body, loads sources into a fresh DuckDBEngine, then compiles.  Returns
    `(compiled_table, destination)` — caller decides how to consume it.
    Compile errors bubble up as `HTTPException(422, str(e))`.

    `on_step_schema` is forwarded to :func:`compile_pipeline` (plan 038
    item 7).
    """
    # Cast the PipelineBase body to Pipeline so downstream code that expects
    # `.sources`, `.output_id`, `.steps` all works — validators already fired.
    pipeline = Pipeline(**body.model_dump())
    decrypt_context_var.set("pipeline_dry_run")
    try:
        sources, (destination, _) = await _resolve(pipeline, s_store, d_store, c_store)
        lookups = await _resolve_lookups(pipeline, lt_store)
        engine = DuckDBEngine()
        registry = BackendRegistry(duckdb_con=engine.con)
        tables = {s.id: load_source(s, registry, conn, creds) for s, conn, creds in sources}
        compiled = compile_pipeline(
            pipeline, tables, output=destination.config,
            lookup_tables=lookups, on_step_schema=on_step_schema,
            engine=engine,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return compiled, destination


@router.post("/pipelines/step-schemas", dependencies=[Depends(requires("pipeline:read"))])
async def step_schemas_pipeline(
    body: PipelineBase,
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
):
    """Return `{step_schemas: {index: [columns]}}` for the given unsaved
    pipeline body (plan 038 item 7).  The frontend uses this so downstream
    editors (filter after aggregate, pivot outputs, etc.) can offer
    autocomplete on newly-materialised columns.
    """
    schemas: dict[int, list[str]] = {}

    def _capture(idx: int, cols: list[str]):
        schemas[idx] = cols

    # A partially-configured pipeline (e.g. aggregate with no aggregations yet)
    # will 422 mid-compile. We still want to return the schemas captured up to
    # the failing step so downstream editors see fresh columns from earlier
    # steps the user just edited — otherwise field autocomplete stays stuck
    # on stale results until the whole pipeline compiles cleanly.
    error: str | None = None
    try:
        await _compile_body_pipeline(
            body, s_store, d_store, c_store, lt_store, on_step_schema=_capture,
        )
    except HTTPException as e:
        error = str(e.detail)
    # JSON keys are strings; matches how the frontend will look them up.
    return {
        "step_schemas": {str(k): v for k, v in schemas.items()},
        "error": error,
    }


@router.post("/pipelines/dry-run", dependencies=[Depends(requires("pipeline:read"))])
async def dry_run_pipeline(
    body: PipelineBase,
    limit: int = 20,
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
):
    """Compile + sample an unsaved pipeline body (plan 038 item 6).

    Mirrors `GET /pipelines/{id}/preview` but the pipeline definition rides
    in the POST body.  Used by the builder split-pane so the preview updates
    as the user edits, before hitting Save.
    """
    compiled, _ = await _compile_body_pipeline(
        body, s_store, d_store, c_store, lt_store,
    )
    try:
        df = compiled.limit(limit).execute()
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    rows = json.loads(df.to_json(orient="records", date_format="iso"))
    return {"rows": rows, "count": len(rows)}


@router.get("/pipelines/{pipeline_id}/preview", dependencies=[Depends(requires("pipeline:read"))])
async def preview_pipeline(
    pipeline_id: str,
    limit: int = 100,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
):
    pipeline = await store.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    decrypt_context_var.set("pipeline_preview")
    try:
        sources, (destination, _) = await _resolve(pipeline, s_store, d_store, c_store)
        lookups = await _resolve_lookups(pipeline, lt_store)
        # Preview runs against whichever backend each source resolves to
        # (postgres source → postgres pushdown). DuckDBEngine here is just
        # the writer glue + raw-SQL rejection helper; the actual per-source
        # execution locus is picked by BackendRegistry.
        engine = DuckDBEngine()
        registry = BackendRegistry(duckdb_con=engine.con)
        tables = {s.id: load_source(s, registry, conn, creds) for s, conn, creds in sources}
        compiled = compile_pipeline(
            pipeline, tables, output=destination.config, lookup_tables=lookups,
            engine=engine,
        )
        df = compiled.limit(limit).execute()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    rows = json.loads(df.to_json(orient="records", date_format="iso"))
    return {"rows": rows, "count": len(rows)}


@router.post("/pipelines/{pipeline_id}/trigger", dependencies=[Depends(requires("pipeline:trigger"))])
async def trigger_pipeline(
    pipeline_id: str,
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
    re_store: RunEventStore = Depends(get_run_event_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
):
    pipeline = await p_store.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    # Fail fast on missing refs before creating a run.
    decrypt_context_var.set("pipeline_run")
    await _resolve(pipeline, s_store, d_store, c_store)
    await _resolve_lookups(pipeline, lt_store)
    # Engine compatibility: catches cases where a pipeline was saved before
    # the engine matrix existed, or a source's connection type changed
    # since save.
    await _validate_engine_compat(pipeline, s_store, d_store, c_store)
    latest_rev = await rev_store.latest_for_pipeline(pipeline_id)
    revision_id = latest_rev.id if latest_rev else None
    run_id = await r_store.create(pipeline_id, revision_id=revision_id)
    # asyncio.create_task in CPython 3.7+ already copies the current context
    # into the new task, so the dte_tenant_id contextvar set by
    # TenantContextMiddleware is automatically available inside _execute_pipeline.
    # We capture copy_context() here explicitly so the intent is searchable
    # and auditable — grep for copy_context to find all tenant-propagation sites.
    _ctx = contextvars.copy_context()

    async def _task_with_context():
        # Re-apply the captured context vars inside the coroutine.
        # This is belt-and-suspenders: create_task already propagates them, but
        # explicit is better than implicit for security-critical code.
        from dte.tenancy import tenant_context_var, get_current_tenant
        _tid = _ctx.run(get_current_tenant)
        tok = tenant_context_var.set(_tid)
        try:
            await _execute_pipeline(
                pipeline_id, run_id, p_store, r_store, re_store,
                s_store, d_store, c_store, lt_store,
            )
        finally:
            tenant_context_var.reset(tok)

    task = asyncio.create_task(_task_with_context())
    run_registry.register(run_id, task)
    return {"run_id": run_id}


@router.get("/runs/{run_id}/events", dependencies=[Depends(requires("run:read"))])
async def list_run_events(
    run_id: str,
    r_store: RunStore = Depends(get_run_store),
    re_store: RunEventStore = Depends(get_run_event_store),
):
    if not await r_store.get(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    events = await re_store.list_for_run(run_id)
    return {"events": events, "count": len(events)}


@router.post("/runs/{run_id}/cancel", dependencies=[Depends(requires("pipeline:trigger"))])
async def cancel_run(run_id: str, r_store: RunStore = Depends(get_run_store)):
    run = await r_store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"Run is already {run.get('status')}")
    cancelled = run_registry.cancel(run_id)
    if not cancelled:
        # No local task — likely a stale run from a previous worker. Best-effort
        # mark it cancelled so operators can move on.
        await r_store.update(run_id, status="failed", error="cancelled (no local task)")
        return {"cancelled": False, "detail": "no live task on this worker"}
    return {"cancelled": True}


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


async def _run_body(
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
    tr = tracer()
    with tr.start_as_current_span("run") as run_span:
        run_span.set_attribute("pipeline_id", pipeline_id)
        run_span.set_attribute("run_id", run_id)

        with tr.start_as_current_span("resolve"):
            pipeline = await p_store.get(pipeline_id)
            sources, (destination, dest_creds) = await _resolve(
                pipeline, s_store, d_store, c_store,
            )
            lookups = await _resolve_lookups(pipeline, lt_store)

        with tr.start_as_current_span("load_sources") as span:
            # Resolve `engine="auto"` from the source composition so
            # pushdown happens for single-source DB pipelines.  The engine
            # instance returned by get_engine is the local orchestrator +
            # writer glue; the *actual* execution locus for each source
            # comes from BackendRegistry (ibis-native backend per
            # connection_type).
            from dte.models.pipeline import resolve_pipeline_engine
            _engine_choice = getattr(pipeline, "engine", None) or "auto"
            _src_ctypes = [conn.connection_type for _, conn, _ in sources]
            _engine_name = resolve_pipeline_engine(_engine_choice, _src_ctypes)
            engine = get_engine(_engine_name)
            registry = BackendRegistry(duckdb_con=engine.con)
            tables = {
                s.id: load_source(s, registry, conn, creds)
                for s, conn, creds in sources
            }
            span.set_attribute("source_count", len(tables))
            span.set_attribute("engine", _engine_name)

        with tr.start_as_current_span("compile"):
            # Compiler emits synchronously; buffer here and flush async.
            events_buf: list[tuple[int, str, str, str | None]] = []

            def _cb(idx, op, status, msg=None):
                events_buf.append((idx, op, status, msg))

            try:
                compiled = compile_pipeline(
                    pipeline, tables,
                    output=destination.config, lookup_tables=lookups,
                    on_step=_cb,
                    engine=engine,
                )
            finally:
                for idx, op, status, msg in events_buf:
                    await re_store.record(run_id, idx, op, status, msg)
            compiled = compiled.limit(settings.run_max_rows)

        with tr.start_as_current_span("write") as span:
            span.set_attribute("destination_type", destination.config.type)
            result = engine.execute(compiled, destination.config, credentials=dest_creds)
            span.set_attribute("rows_written", result["rows_written"])
    await r_store.update(
        run_id,
        status="completed",
        rows_written=result["rows_written"],
        location=result["location"],
    )
    _log.info(
        "run completed",
        extra={"pipeline_id": pipeline_id, "rows_written": result["rows_written"]},
    )
