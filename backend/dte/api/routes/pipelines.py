from __future__ import annotations

import asyncio
import contextvars
import json

import ibis

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

BULK_DELETE_LIMIT = 200


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=BULK_DELETE_LIMIT)


class TriggerRequest(BaseModel):
    """Optional trigger-time params. Keys are user-defined; values are
    strings substituted into filter/map `{{params.<key>}}` placeholders."""

    params: dict[str, str] = Field(default_factory=dict)
    # Eval pipelines are bound to a corpus at trigger time, not at save time,
    # so the same extraction config can be scored against several sets.
    eval_set_id: str | None = None
    # Set by the sweep launcher so N runs of one matrix share an id.
    sweep_id: str | None = None

from dte.api.deps import (
    get_connection_store,
    get_current_user,
    get_destination_store,
    get_eval_example_store,
    get_eval_set_store,
    get_lookup_table_store,
    get_pipeline_revision_store,
    get_pipeline_store,
    get_run_event_store,
    get_run_store,
    get_source_store,
)
from dte.compiler.ibis_compiler import compile_pipeline
from dte.compiler.interpolate import (
    InterpolationError,
    ParamValidationError,
    interpolate_pipeline,
    resolve_context,
)
from dte.pipelines.diff import diff_pipeline, summarise_diff
from dte.config import get_settings
from dte.engine.duckdb_engine import DuckDBEngine  # noqa: F401 — still used as type hint fallback
from dte.engine.registry import get_engine
from dte.logging import decrypt_context_var, get_logger
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
    EvalExampleStore,
    EvalSetStore,
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

# Process-local registry of in-flight asyncio tasks for the flag-off
# (DTE_JOB_QUEUE_ENABLED=False) trigger path — the pre-plan-046 `dte.runs`
# module's job, now private here since it's only ever consulted by
# `cancel_run` for runs with no `job_id`. Distributed (job-queue) runs
# don't need this at all: `cancel_run` cancels those via
# `procrastinate`'s cancel-by-job-id, which works regardless of which
# worker pod picked the job up. This registry remains process-local by
# nature — sufficient for a single-container self-hosted deployment,
# the only topology that ever runs with the flag off.
_local_run_tasks: dict[str, asyncio.Task] = {}


def _register_local_task(run_id: str, task: asyncio.Task) -> None:
    _local_run_tasks[run_id] = task
    task.add_done_callback(lambda _t, rid=run_id: _local_run_tasks.pop(rid, None))


def _cancel_local_task(run_id: str) -> bool:
    task = _local_run_tasks.get(run_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


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


def _parse_params_query(raw: str | None) -> dict[str, str] | None:
    """Decode `?params=<json>` into a str-keyed str-valued dict.

    Rejects non-object JSON or non-string values with 422 so the caller can't
    smuggle typed values into what will get str-substituted into SQL anyway.
    """
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"invalid params json: {e}")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="params must be a JSON object")
    for k, v in parsed.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise HTTPException(status_code=422, detail="params keys and values must be strings")
    return parsed


def _eval_run_fields(eval_set_id: str | None, sweep_id: str | None) -> dict:
    """Only emit the eval columns when they were supplied.

    A transform run must not write `eval_set_id = NULL` explicitly — the
    column is how the leaderboard finds eval runs, and writing it on every
    run would make the partial index useless."""
    fields: dict = {}
    if eval_set_id:
        fields["eval_set_id"] = eval_set_id
    if sweep_id:
        fields["sweep_id"] = sweep_id
    return fields


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
    # Quality and eval pipelines both write nowhere, so neither requires a
    # destination. Without this an eval pipeline is rejected at save for a
    # missing `output_id` it is never supposed to have.
    is_quality = getattr(pipeline, "pipeline_type", "transform") in ("quality", "eval")
    missing_dest = None
    if not is_quality:
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

    # Quality and eval pipelines both write nowhere, so neither requires a
    # destination. Without this an eval pipeline is rejected at save for a
    # missing `output_id` it is never supposed to have.
    is_quality = getattr(pipeline, "pipeline_type", "transform") in ("quality", "eval")
    dest_tuple: tuple[str, str] | None = None
    if not is_quality:
        destination = await d_store.get(pipeline.output_id)
        if not destination:
            raise HTTPException(status_code=422, detail=f"Destination not found: {pipeline.output_id}")
        dest_conn = await c_store.get(destination.connection_id)
        if not dest_conn:
            raise HTTPException(
                status_code=422,
                detail=f"Destination '{destination.id}' references missing connection '{destination.connection_id}'",
            )
        dest_tuple = (destination.id, dest_conn.connection_type)

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
            destination=dest_tuple,
        )
    except EngineIncompatible as e:
        raise HTTPException(status_code=422, detail=e.payload()) from e

    return resolved


async def _check_shared_fs_guard(
    pipeline: PipelineBase,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
) -> None:
    """Reject (422) a trigger when the job queue is on, the output
    filesystem isn't shared across pods, and the pipeline touches a
    `local_fs` source or destination (plan 046 "Sharp edge 1"). Only
    called when `settings.job_queue_enabled and not settings.shared_output_fs`
    — assumes `_resolve`/`_resolve_sources` already confirmed every id
    exists, so a missing lookup here is silently skipped rather than
    re-raised (that 422 already fired).
    """
    offending: list[str] = []
    for sid in pipeline.sources:
        source = await s_store.get(sid)
        if not source:
            continue
        conn = await c_store.get(source.connection_id)
        if conn and conn.connection_type == "local_fs":
            offending.append(sid)

    # Quality and eval pipelines both write nowhere, so neither requires a
    # destination. Without this an eval pipeline is rejected at save for a
    # missing `output_id` it is never supposed to have.
    is_quality = getattr(pipeline, "pipeline_type", "transform") in ("quality", "eval")
    if not is_quality:
        destination = await d_store.get(pipeline.output_id)
        if destination:
            dest_conn = await c_store.get(destination.connection_id)
            if dest_conn and dest_conn.connection_type == "local_fs":
                offending.append(destination.id)

    if offending:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "local_fs_not_shared",
                "message": (
                    "DTE_JOB_QUEUE_ENABLED is on and DTE_SHARED_OUTPUT_FS is "
                    "off: local_fs sources/destinations can't cross the "
                    "API/worker process boundary. Use an s3/gcs/azure "
                    "connection, or set DTE_SHARED_OUTPUT_FS=true if this "
                    "deployment mounts a shared RWX volume."
                ),
                "offending_ids": offending,
            },
        )


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
    try:
        await store.save(Pipeline(**pipeline.model_dump()))
    except ValueError as e:  # name collision on UNIQUE(tenant_id, name)
        raise HTTPException(status_code=409, detail=str(e))
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
    try:
        await store.save(row)
    except ValueError as e:  # name collision
        raise HTTPException(status_code=409, detail=str(e))
    await _record_revision(pipeline, rev_store, user)
    return row


@router.post("/pipelines/bulk-delete", dependencies=[Depends(requires("pipeline:delete"))])
async def bulk_delete_pipelines(
    body: BulkDeleteRequest,
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
):
    ids = list(dict.fromkeys(body.ids))
    deleted: list[str] = []
    not_found: list[str] = []
    for pid in ids:
        if not await p_store.get(pid):
            not_found.append(pid)
            continue
        await r_store.delete_for_pipeline(pid)
        await p_store.delete(pid)
        deleted.append(pid)
    return {"deleted": deleted, "not_found": not_found, "blocked": []}


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


def _normalise_sweepable_keys(step: dict) -> dict:
    """Fill the structure-step keys a sweep will want to override.

    `apply_cell` refuses to *create* a leaf that does not already exist —
    a `params.model` sweep against a step that never named a model raises
    "no 'model' under 'params'". That guard is worth keeping: it is what
    stops a typo'd axis silently becoming N identical cells that read as
    "this setting makes no difference". So the twin is filled in instead of
    the guard being loosened.

    Only ever fills what is absent. An explicitly pinned model is the
    user's decision and stays put; the sweep overrides it per cell anyway.

    `regex` deliberately gets no `model` param — it makes no model calls,
    and the key would surface in the wizard as an axis that changes nothing.
    """
    from dte.providers.structure import DEFAULT_CLAUDE_MODEL, DEFAULT_OPENAI_MODEL

    step = dict(step)
    step["params"] = dict(step.get("params") or {})
    step["model"] = dict(step.get("model") or {})
    step["model"].setdefault("instructions", "")

    defaults = {"claude": DEFAULT_CLAUDE_MODEL, "openai": DEFAULT_OPENAI_MODEL}
    default_model = defaults.get(step.get("provider") or "claude")
    if default_model and not step["params"].get("model"):
        step["params"]["model"] = default_model
    return step


@router.post(
    "/pipelines/{pipeline_id}/as-eval",
    dependencies=[Depends(requires("eval:write"))],
)
async def pipeline_as_eval(
    pipeline_id: str,
    response: Response,
    p_store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
):
    """The eval twin of an extraction pipeline — same steps, no destination.

    Until this existed, `pipeline_type` could only be chosen on create: the
    builder's control is mounted by `/pipelines/new` and the edit route is
    a redirect. Evaluating a pipeline you already had therefore meant
    rebuilding it by hand in a second pipeline and retyping every field —
    at which point the comparison is partly measuring your typing.

    Idempotent, because Compare is a button people press twice. A second
    press returns the existing twin rather than accumulating
    `__eval__eval`, each with its own runs diluting one leaderboard.
    """
    source = await p_store.get(pipeline_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # An eval pipeline is already its own twin. Returning it keeps the
    # caller's flow identical whichever kind of pipeline they pressed
    # Compare on.
    if getattr(source, "pipeline_type", "transform") == "eval":
        return {"pipeline_id": pipeline_id, "created": False}

    steps = list(getattr(source, "steps", None) or [])
    idx = next(
        (i for i, s in enumerate(steps) if isinstance(s, dict) and s.get("op") == "structure"),
        None,
    )
    if idx is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "comparing configs means varying a structure step, and this "
                "pipeline has none — there is nothing to compare"
            ),
        )

    # Labels join to extracted rows by document hash, which only a documents
    # source produces. Refusing here names the real problem; allowing it
    # produces a twin whose every run scores a flat zero.
    kinds = {}
    for sid in getattr(source, "sources", None) or []:
        row = await s_store.get(sid)
        if row is not None:
            kinds[sid] = row.source_type
    if "documents" not in kinds.values():
        raise HTTPException(
            status_code=422,
            detail=(
                f"pipeline '{pipeline_id}' reads {sorted(kinds.values()) or 'nothing'}, "
                "but scoring needs a 'documents' source: labels are keyed by "
                "document hash and no other source kind produces one"
            ),
        )

    twin_id = f"{pipeline_id}__eval"
    if await p_store.get(twin_id):
        return {"pipeline_id": twin_id, "created": False}

    from dte.evals.sweep import detached_copy

    twin = detached_copy(source)
    twin.id = twin_id
    twin.name = f"{source.name} · eval"
    twin.pipeline_type = "eval"
    twin.output_id = None
    twin_steps = list(twin.steps)
    twin_steps[idx] = _normalise_sweepable_keys(twin_steps[idx])
    twin.steps = twin_steps
    await p_store.save(twin)
    response.status_code = 201
    return {"pipeline_id": twin_id, "created": True}


@router.get(
    "/pipelines/{pipeline_id}/revisions",
    dependencies=[Depends(requires("pipeline:read"))],
)
async def list_pipeline_revisions(
    pipeline_id: str,
    response: Response,
    limit: int = 100,
    offset: int = 0,
    p_store: PipelineStore = Depends(get_pipeline_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
):
    if not await p_store.get(pipeline_id):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    response.headers["X-Total-Count"] = str(
        await rev_store.count_for_pipeline(pipeline_id)
    )
    return await rev_store.list_for_pipeline(pipeline_id, limit=limit, offset=offset)


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


async def _resolve_sources(
    pipeline: Pipeline,
    s_store: SourceStore,
    c_store: ConnectionStore,
) -> list[tuple[Source, "Connection", dict]]:
    """Resolve only sources (no destination) — used for quality pipelines."""
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
    return sources


async def _compile_body_pipeline(
    body: PipelineBase,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
    lt_store: LookupTableStore,
    *,
    on_step_schema=None,
    on_step_sql=None,
    params: dict[str, str] | None = None,
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
    # Quality and eval pipelines both write nowhere, so neither requires a
    # destination. Without this an eval pipeline is rejected at save for a
    # missing `output_id` it is never supposed to have.
    is_quality = getattr(pipeline, "pipeline_type", "transform") in ("quality", "eval")
    try:
        pipeline = interpolate_pipeline(pipeline, resolve_context(pipeline, params))
        if is_quality:
            sources = await _resolve_sources(pipeline, s_store, c_store)
            destination = None
        else:
            sources, (destination, _) = await _resolve(pipeline, s_store, d_store, c_store)
        lookups = await _resolve_lookups(pipeline, lt_store)
        engine = DuckDBEngine()
        registry = BackendRegistry(duckdb_con=engine.con)
        tables = {s.id: load_source(s, registry, conn, creds) for s, conn, creds in sources}
        compiled = compile_pipeline(
            pipeline, tables,
            output=destination.config if destination else None,
            lookup_tables=lookups, on_step_schema=on_step_schema,
            on_step_sql=on_step_sql,
            engine=engine,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return compiled, destination, engine


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
    params: str | None = None,
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
):
    """Compile + sample an unsaved pipeline body (plan 038 item 6).

    Mirrors `GET /pipelines/{id}/preview` but the pipeline definition rides
    in the POST body.  Used by the builder split-pane so the preview updates
    as the user edits, before hitting Save.

    Response also includes `step_sqls` (per-step compiled SQL) and
    `final_sql` (the LIMIT-wrapped SELECT that actually executes) — plan-039.
    A compile error is returned as 200 with `error` populated and whatever
    step SQLs were captured before the failing step, so the SQL panel can
    keep rendering as the user edits.
    """
    step_sqls: dict[int, str] = {}

    def _capture_sql(idx: int, sql: str):
        step_sqls[idx] = sql

    error: str | None = None
    compiled = None
    engine = None
    try:
        parsed_params = _parse_params_query(params)
    except HTTPException as e:
        error = str(e.detail)
        parsed_params = None
    if error is None:
        try:
            compiled, _, engine = await _compile_body_pipeline(
                body, s_store, d_store, c_store, lt_store,
                on_step_sql=_capture_sql,
                params=parsed_params,
            )
        except HTTPException as e:
            error = str(e.detail)

    rows: list = []
    final_sql: str | None = None
    if compiled is not None:
        dialect = getattr(engine, "dialect", "duckdb")
        try:
            final_sql = str(ibis.to_sql(compiled.limit(limit), dialect=dialect))
        except Exception:
            final_sql = None
        try:
            df = compiled.limit(limit).execute()
            rows = json.loads(df.to_json(orient="records", date_format="iso"))
        except Exception as e:
            error = str(e)

    return {
        "rows": rows,
        "count": len(rows),
        "step_sqls": {str(k): v for k, v in step_sqls.items()},
        "final_sql": final_sql,
        "error": error,
    }


@router.get("/pipelines/{pipeline_id}/preview", dependencies=[Depends(requires("pipeline:read"))])
async def preview_pipeline(
    pipeline_id: str,
    limit: int = 100,
    params: str | None = None,
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

    step_sqls: dict[int, str] = {}

    def _capture_sql(idx: int, sql: str):
        step_sqls[idx] = sql

    # Quality and eval pipelines both write nowhere, so neither requires a
    # destination. Without this an eval pipeline is rejected at save for a
    # missing `output_id` it is never supposed to have.
    is_quality = getattr(pipeline, "pipeline_type", "transform") in ("quality", "eval")
    error: str | None = None
    compiled = None
    engine = None
    try:
        parsed_params = _parse_params_query(params)
        pipeline = interpolate_pipeline(pipeline, resolve_context(pipeline, parsed_params))
        if is_quality:
            sources = await _resolve_sources(pipeline, s_store, c_store)
            destination = None
        else:
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
            pipeline, tables,
            output=destination.config if destination else None,
            lookup_tables=lookups, engine=engine, on_step_sql=_capture_sql,
        )
    except HTTPException:
        raise
    except Exception as e:
        error = str(e)

    rows: list = []
    final_sql: str | None = None
    if compiled is not None:
        dialect = getattr(engine, "dialect", "duckdb")
        try:
            final_sql = str(ibis.to_sql(compiled.limit(limit), dialect=dialect))
        except Exception:
            final_sql = None
        try:
            df = compiled.limit(limit).execute()
            rows = json.loads(df.to_json(orient="records", date_format="iso"))
        except Exception as e:
            error = str(e)

    return {
        "rows": rows,
        "count": len(rows),
        "step_sqls": {str(k): v for k, v in step_sqls.items()},
        "final_sql": final_sql,
        "error": error,
    }


async def start_eval_run(
    pipeline_id: str,
    *,
    eval_set_id: str,
    sweep_id: str | None = None,
    p_store: PipelineStore,
    r_store: RunStore,
    re_store: RunEventStore,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
    lt_store: LookupTableStore,
    es_store=None,
    ee_store=None,
) -> str:
    """Start one eval run and return its run id.

    Factored out of `trigger_pipeline` so the sweep launcher starts runs the
    same way a manual trigger does — including the job-queue/in-process
    split. A second, parallel way to start a run is how the two drift until
    one of them stops recording something the other does.
    """
    settings = get_settings()
    if settings.job_queue_enabled:
        from dte.tenancy import get_current_tenant
        from dte.worker.tasks import enqueue_run
        run_id, _job = await enqueue_run(
            pipeline_id, None, tenant_id=get_current_tenant(),
        )
        await r_store.update(run_id, **_eval_run_fields(eval_set_id, sweep_id))
        return run_id

    run_id = await r_store.create(pipeline_id)
    await r_store.update(run_id, **_eval_run_fields(eval_set_id, sweep_id))
    _ctx = contextvars.copy_context()

    async def _task_with_context():
        from dte.tenancy import get_current_tenant, tenant_context_var
        from dte.worker.tasks import _execute_pipeline
        tok = tenant_context_var.set(_ctx.run(get_current_tenant))
        try:
            await _execute_pipeline(
                pipeline_id, run_id, p_store, r_store, re_store,
                s_store, d_store, c_store, lt_store,
                es_store=es_store, ee_store=ee_store,
            )
        finally:
            tenant_context_var.reset(tok)

    _register_local_task(run_id, asyncio.create_task(_task_with_context()))
    return run_id


async def materialise_pipeline_rows(
    pipeline: Pipeline,
    s_store: SourceStore,
    c_store: ConnectionStore,
    lt_store: LookupTableStore,
    limit: int = 500,
) -> list[dict]:
    """Compile a destination-less pipeline and return its rows.

    Extracted from the preview path so the consensus bootstrap can run
    several variants over one corpus without duplicating source
    resolution. Deliberately shares preview's shape rather than the run
    path's: bootstrap writes no run rows and records no events — it is a
    read of what a config *would* produce.

    Cheap to call repeatedly despite appearances: plan 050 caches extract
    results by document content, so N variants over one corpus parse each
    PDF once and only the structure calls vary.
    """
    decrypt_context_var.set("pipeline_preview")
    sources = await _resolve_sources(pipeline, s_store, c_store)
    lookups = await _resolve_lookups(pipeline, lt_store)
    engine = DuckDBEngine()
    registry = BackendRegistry(duckdb_con=engine.con)
    tables = {s.id: load_source(s, registry, conn, creds) for s, conn, creds in sources}
    compiled = compile_pipeline(pipeline, tables, lookup_tables=lookups, engine=engine)
    df = compiled.limit(limit).execute()
    return json.loads(df.to_json(orient="records", date_format="iso"))


@router.post("/pipelines/{pipeline_id}/trigger", dependencies=[Depends(requires("pipeline:trigger"))])
async def trigger_pipeline(
    pipeline_id: str,
    body: TriggerRequest | None = None,
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
    re_store: RunEventStore = Depends(get_run_event_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
    es_store: EvalSetStore = Depends(get_eval_set_store),
    ee_store: EvalExampleStore = Depends(get_eval_example_store),
):
    pipeline = await p_store.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    # Fail fast on missing refs before creating a run.
    decrypt_context_var.set("pipeline_run")
    _ptype = getattr(pipeline, "pipeline_type", "transform") or "transform"
    if _ptype in ("quality", "eval"):
        await _resolve_sources(pipeline, s_store, c_store)
    else:
        await _resolve(pipeline, s_store, d_store, c_store)

    # An eval run with no corpus would compile, produce rows, and score
    # nothing — a green run that measured zero documents. Reject at trigger.
    eval_set_id = body.eval_set_id if body else None
    sweep_id = body.sweep_id if body else None
    if _ptype == "eval" and not eval_set_id:
        raise HTTPException(
            status_code=422,
            detail="eval pipelines must be triggered with an eval_set_id",
        )
    if eval_set_id and _ptype != "eval":
        raise HTTPException(
            status_code=422,
            detail=f"eval_set_id is only valid for eval pipelines (this one is {_ptype!r})",
        )
    if eval_set_id:
        # The pipeline must read the corpus the labels describe. Labels join
        # by doc_key (sha256 of the document), so a pipeline pointed at a
        # different documents source produces hashes that match nothing: the
        # run completes green having scored zero documents, which reads as a
        # broken extractor rather than a mismatched corpus.
        #
        # Presence, not exclusivity — a pipeline may carry other sources
        # alongside the corpus and still be scoring the right documents.
        _set = await es_store.get(eval_set_id)
        if _set is None:
            raise HTTPException(status_code=422, detail=f"eval set not found: {eval_set_id}")
        if _set.source_id not in (pipeline.sources or []):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"eval set '{eval_set_id}' labels documents from source "
                    f"'{_set.source_id}', but pipeline '{pipeline_id}' reads "
                    f"{list(pipeline.sources or [])}. Scoring these together "
                    f"would match no labels and report zero."
                ),
            )
    await _resolve_lookups(pipeline, lt_store)
    # Engine compatibility: catches cases where a pipeline was saved before
    # the engine matrix existed, or a source's connection type changed
    # since save.
    await _validate_engine_compat(pipeline, s_store, d_store, c_store)
    settings = get_settings()
    if settings.job_queue_enabled and not settings.shared_output_fs:
        # plan 046 "Sharp edge 1": a local_fs source/destination is only
        # readable by whichever process wrote/reads it. With execution
        # split across an API pod and a worker pod (and no shared RWX
        # volume), reject at trigger time rather than failing mid-run.
        await _check_shared_fs_guard(pipeline, s_store, d_store, c_store)
    user_params = (body.params if body else {}) or {}
    # Resolve the interpolation context up-front so `now`/`today` snapshot at
    # trigger time (not at compile time deep inside the task) and get
    # persisted alongside the caller's params for post-hoc inspection.
    try:
        run_context = resolve_context(pipeline, user_params)
        interpolate_pipeline(pipeline, run_context)  # early fail on unknown vars
    except ParamValidationError as e:
        raise HTTPException(status_code=422, detail=e.payload())
    except InterpolationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    latest_rev = await rev_store.latest_for_pipeline(pipeline_id)
    revision_id = latest_rev.id if latest_rev else None

    if settings.job_queue_enabled:
        # Distributed path (plan 046): enqueue a procrastinate job instead
        # of spawning an in-process task. A separate `python -m dte.worker`
        # process executes it.
        # Local import: dte.worker.tasks imports `_run_body` from this
        # module at import time — importing it back at module scope here
        # would be circular (same reason `_execute_pipeline` is imported
        # locally in `_task_with_context` below).
        from dte.tenancy import get_current_tenant
        from dte.worker.tasks import enqueue_run
        run_id, _job_id = await enqueue_run(
            pipeline_id, revision_id, tenant_id=get_current_tenant(),
        )
        await r_store.update(
            run_id, params=run_context, **_eval_run_fields(eval_set_id, sweep_id)
        )
        return {"run_id": run_id}

    run_id = await r_store.create(pipeline_id, revision_id=revision_id)
    await r_store.update(
        run_id, params=run_context, **_eval_run_fields(eval_set_id, sweep_id)
    )
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
        # Local import: dte.worker.tasks imports `_run_body` from this module
        # at import time, so importing it back at module scope here would be
        # circular. _execute_pipeline itself is unchanged by plan 046 — only
        # its address moved (dte.api.routes.pipelines -> dte.worker.tasks).
        from dte.worker.tasks import _execute_pipeline
        _tid = _ctx.run(get_current_tenant)
        tok = tenant_context_var.set(_tid)
        try:
            await _execute_pipeline(
                pipeline_id, run_id, p_store, r_store, re_store,
                s_store, d_store, c_store, lt_store,
                es_store=es_store, ee_store=ee_store,
            )
        finally:
            tenant_context_var.reset(tok)

    task = asyncio.create_task(_task_with_context())
    _register_local_task(run_id, task)
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

    job_id = run.get("job_id")
    if job_id:
        # Distributed path (plan 046): queue-native cancel. Works
        # regardless of which worker pod picked up the job — no
        # process-local state to consult. abort=True covers both a job
        # still `todo` (marks it cancelled, never dequeued) and a job
        # `doing` (procrastinate's worker cancels the asyncio task
        # running it; the existing `except asyncio.CancelledError` handler
        # in dte.worker.tasks._execute_pipeline already writes
        # status=failed, error=cancelled).
        from dte.worker.app import get_running_app

        app = await get_running_app()
        cancelled = await app.job_manager.cancel_job_by_id_async(job_id, abort=True)
        if not cancelled:
            # No job in a cancellable state — it already reached a
            # terminal status between our read above and this call.
            await r_store.update(run_id, status="failed", error="cancelled (job already finished)")
            return {"cancelled": False, "detail": "job already finished"}
        return {"cancelled": True}

    cancelled = _cancel_local_task(run_id)
    if not cancelled:
        # No local task — likely a stale run from a previous worker. Best-effort
        # mark it cancelled so operators can move on.
        await r_store.update(run_id, status="failed", error="cancelled (no local task)")
        return {"cancelled": False, "detail": "no live task on this worker"}
    return {"cancelled": True}


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
    *,
    es_store: "EvalSetStore | None" = None,
    ee_store: "EvalExampleStore | None" = None,
):
    settings = get_settings()
    tr = tracer()
    with tr.start_as_current_span("run") as run_span:
        run_span.set_attribute("pipeline_id", pipeline_id)
        run_span.set_attribute("run_id", run_id)

        with tr.start_as_current_span("resolve"):
            pipeline = await p_store.get(pipeline_id)
            # Reuse the context that was frozen at trigger time so `now`/`today`
            # don't drift and the resolved values match what the run record shows.
            run_row = await r_store.get(run_id)
            run_context = (run_row or {}).get("params") or resolve_context(pipeline)
            pipeline = interpolate_pipeline(pipeline, run_context)
            pipeline_type = getattr(pipeline, "pipeline_type", "transform") or "transform"

            if pipeline_type in ("quality", "eval"):
                # Neither writes anywhere: a quality run reports checks, an
                # eval run reports scores. Resolve sources only.
                sources = await _resolve_sources(pipeline, s_store, c_store)
                destination = None
                dest_creds = None
            else:
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

        if pipeline_type == "quality":
            # Quality pipeline: compile with inline check callbacks, skip write.
            with tr.start_as_current_span("compile"):
                events_buf: list[tuple[int, str, str, str | None]] = []
                quality_results = []
                step_sqls: dict[int, str] = {}

                def _cb(idx, op, status, msg=None):
                    events_buf.append((idx, op, status, msg))

                def _on_quality_result(step_idx, qresult):
                    quality_results.append(qresult)

                def _capture_sql(idx: int, sql: str):
                    step_sqls[idx] = sql

                try:
                    compile_pipeline(
                        pipeline, tables,
                        lookup_tables=lookups,
                        on_step=_cb,
                        engine=engine,
                        on_quality_result=_on_quality_result,
                        on_step_sql=_capture_sql,
                    )
                finally:
                    for idx, op, status, msg in events_buf:
                        await re_store.record(run_id, idx, op, status, msg)
            if step_sqls:
                await r_store.update(run_id, sql_query={"step_sqls": {str(k): v for k, v in step_sqls.items()}})

            await r_store.set_quality(run_id, [r.model_dump() for r in quality_results])

            failed_hard = any(not r.passed and r.severity == "fail" for r in quality_results)
            failed_warn = any(not r.passed and r.severity == "warn" for r in quality_results)
            final_status = (
                "failed_quality" if failed_hard
                else "completed_with_warnings" if failed_warn
                else "completed"
            )
            await r_store.update(run_id, status=final_status, rows_written=0, location=None)
            _log.info(
                "quality run completed",
                extra={"pipeline_id": pipeline_id, "checks": len(quality_results), "status": final_status},
            )
            return

        if pipeline_type == "eval":
            await _run_eval_body(
                pipeline, run_id, run_row, tables, lookups, engine,
                r_store, re_store, es_store, ee_store, tr,
            )
            return

        # Transform pipeline: existing compile → write → post-run contracts path.
        with tr.start_as_current_span("compile"):
            # Compiler emits synchronously; buffer here and flush async.
            events_buf: list[tuple[int, str, str, str | None]] = []
            step_sqls: dict[int, str] = {}

            def _cb(idx, op, status, msg=None):
                events_buf.append((idx, op, status, msg))

            def _capture_sql(idx: int, sql: str):
                step_sqls[idx] = sql

            try:
                compiled = compile_pipeline(
                    pipeline, tables,
                    output=destination.config, lookup_tables=lookups,
                    on_step=_cb,
                    on_step_sql=_capture_sql,
                    engine=engine,
                )
            finally:
                for idx, op, status, msg in events_buf:
                    await re_store.record(run_id, idx, op, status, msg)
            dialect = getattr(engine, "dialect", "duckdb")
            final_sql: str | None = None
            try:
                final_sql = str(ibis.to_sql(compiled.limit(settings.run_max_rows), dialect=dialect))
            except Exception:
                pass
            if step_sqls or final_sql:
                await r_store.update(run_id, sql_query={
                    "step_sqls": {str(k): v for k, v in step_sqls.items()},
                    "final_sql": final_sql,
                })
            compiled = compiled.limit(settings.run_max_rows)

        with tr.start_as_current_span("write") as span:
            span.set_attribute("destination_type", destination.config.type)
            result = engine.execute(
                compiled, destination.config, credentials=dest_creds, run_id=run_id
            )
            span.set_attribute("rows_written", result["rows_written"])

        with tr.start_as_current_span("quality") as q_span:
            contracts = getattr(pipeline, "quality_contracts", []) or []
            quality_results = []
            if contracts:
                from dte.quality.evaluator import evaluate_contracts
                quality_results = evaluate_contracts(contracts, destination.config, engine.con)
                q_span.set_attribute("contracts_evaluated", len(contracts))
                q_span.set_attribute("contracts_passed", sum(1 for r in quality_results if r.passed))
            await r_store.set_quality(run_id, [r.model_dump() for r in quality_results])

    failed_hard = any(not r.passed and r.severity == "fail" for r in quality_results)
    failed_warn = any(not r.passed and r.severity == "warn" for r in quality_results)
    final_status = (
        "failed_quality" if failed_hard
        else "completed_with_warnings" if failed_warn
        else "completed"
    )
    await r_store.update(
        run_id,
        status=final_status,
        rows_written=result["rows_written"],
        location=result["location"],
    )
    _log.info(
        "run completed",
        extra={"pipeline_id": pipeline_id, "rows_written": result["rows_written"], "status": final_status},
    )


async def _run_eval_body(
    pipeline,
    run_id: str,
    run_row: dict | None,
    tables: dict,
    lookups: dict,
    engine,
    r_store: RunStore,
    re_store: RunEventStore,
    es_store: "EvalSetStore | None",
    ee_store: "EvalExampleStore | None",
    tr,
):
    """Compile, materialise, join to labels, score (plan 051 task 7).

    Scoring runs here rather than as a compiler op for a concrete reason:
    precision/recall over a corpus *is* an aggregation, and
    `PipelineBase._validate_steps` rejects `aggregate` outside transform
    pipelines. Relaxing that guard to let a "score" step exist would trade a
    narrow rule for a user-visible step they have to wire correctly. Doing it
    in the runner mirrors `evaluate_contracts` in the quality branch, and
    keeps the compiler a pure table -> table function.

    The eval set is bound at trigger time and recorded on the run row, so a
    run always carries what it was scored against.
    """
    from dte.evals.cost import throughput_stats
    from dte.evals.digest import config_digest
    from dte.evals.runner import join_and_score

    eval_set_id = (run_row or {}).get("eval_set_id")
    if not eval_set_id:
        raise ValueError(
            "eval pipeline triggered without an eval_set_id — nothing to score "
            "against; pass eval_set_id when triggering"
        )
    if es_store is None or ee_store is None:
        # Lazy: only an eval run needs these, and building one requires
        # DATABASE_URL. Resolving them eagerly on the shared run path would
        # make every transform run depend on config it never reads.
        from dte.api.deps import get_eval_example_store, get_eval_set_store
        es_store = es_store or get_eval_set_store()
        ee_store = ee_store or get_eval_example_store()

    eval_set = await es_store.get(eval_set_id)
    if eval_set is None:
        raise ValueError(f"eval set not found: {eval_set_id}")

    specs = eval_set.to_field_specs()
    # Pin the label version *before* compiling. Labels can be edited while a
    # run is in flight; recording the version we actually read is what lets
    # the leaderboard grey out runs whose labels have since changed instead of
    # silently comparing against a moved target.
    labels_version = eval_set.labels_version
    examples = await ee_store.list_for_set(eval_set_id, limit=10**6)

    with tr.start_as_current_span("compile"):
        events_buf: list[tuple[int, str, str, str | None]] = []

        def _cb(idx, op, status, msg=None):
            events_buf.append((idx, op, status, msg))

        try:
            compiled = compile_pipeline(
                pipeline, tables,
                lookup_tables=lookups,
                on_step=_cb,
                engine=engine,
            )
        finally:
            for idx, op, status, msg in events_buf:
                await re_store.record(run_id, idx, op, status, msg)

    with tr.start_as_current_span("materialise") as span:
        settings = get_settings()
        df = compiled.limit(settings.run_max_rows).execute()
        rows = json.loads(df.to_json(orient="records", date_format="iso"))
        span.set_attribute("rows", len(rows))

    with tr.start_as_current_span("score") as span:
        scores = join_and_score(rows, examples, specs, collect_failures=True)
        # Cost, cache-hit rate and latency come from the same rows that were
        # scored, so the spend reported always describes the work the score
        # is based on. Plan 051's economic claim — caching makes sweeps
        # affordable — is only checkable once these are on screen.
        scores["throughput"] = throughput_stats(rows)
        digest = config_digest(pipeline)
        span.set_attribute("macro_f1", scores.get("macro_f1") or -1.0)
        span.set_attribute("n", scores.get("n", 0))

    # Regression check against the previous run of the *same* config. A drop
    # here means nothing about the pipeline changed and the score moved anyway
    # — the provider shifted under you, which is the whole point of recording
    # a digest.
    regression = await _detect_eval_regression(
        r_store, eval_set_id, digest, labels_version, run_id, scores
    )
    if regression:
        scores["regression"] = regression

    await r_store.update(
        run_id,
        status="completed_with_warnings" if regression else "completed",
        rows_written=scores.get("n", 0),
        location=None,
        eval_set_id=eval_set_id,
        labels_version=labels_version,
        config_digest=digest,
        scores=scores,
    )
    _log.info(
        "eval run completed",
        extra={
            "eval_set_id": eval_set_id,
            "macro_f1": scores.get("macro_f1"),
            "n": scores.get("n"),
            "regressed": bool(regression),
        },
    )


# Default drop, in F1 points, that counts as a regression.
EVAL_REGRESSION_THRESHOLD = 0.03


async def _detect_eval_regression(
    r_store: RunStore,
    eval_set_id: str,
    digest: str,
    labels_version: int,
    run_id: str,
    scores: dict,
) -> dict | None:
    """Compare against the most recent completed run at the same digest.

    Gated on three things, all of which must hold before this warns:

    - **Same `config_digest`** — otherwise the "regression" is just a config
      change, which is a result, not an alert.
    - **Same `labels_version`** — comparing across a label edit measures the
      labels, not the extractor.
    - **The drop clears the Wilson interval** — a nightly job that pages
      someone on sampling noise gets muted within a week, and then it is worth
      nothing on the night it is right.
    """
    current = scores.get("macro_f1")
    if current is None:
        return None
    try:
        history = await r_store.list_for_eval_set(eval_set_id, limit=50)
    except Exception:  # noqa — a failed comparison must never fail the run
        _log.exception("regression lookup failed", extra={"run_id": run_id})
        return None

    for prior in history:
        if prior.get("id") == run_id:
            continue
        if prior.get("config_digest") != digest:
            continue
        if prior.get("labels_version") != labels_version:
            continue
        prior_scores = prior.get("scores") or {}
        previous = prior_scores.get("macro_f1")
        if previous is None:
            continue

        drop = previous - current
        if drop < EVAL_REGRESSION_THRESHOLD:
            return None

        lo, hi = (scores.get("macro_f1_interval") or [0.0, 1.0])[:2]
        prior_interval = prior_scores.get("macro_f1_interval") or [0.0, 1.0]
        if prior_interval[0] <= hi and lo <= prior_interval[1]:
            # Intervals overlap: the drop is not distinguishable from noise.
            return None

        return {
            "previous_run_id": prior.get("id"),
            "previous_macro_f1": previous,
            "current_macro_f1": current,
            "drop": drop,
            "threshold": EVAL_REGRESSION_THRESHOLD,
        }
    return None
