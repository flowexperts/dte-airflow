from __future__ import annotations

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
    # Plan 093, the sweep's shape: a pipeline reading a metered source
    # (BigQuery, Snowflake) returns an estimate and starts nothing until the
    # caller sends confirm=true.
    confirm: bool = False


class PipelineEstimate(BaseModel):
    """What a run of this pipeline would scan on its warehouse sources."""
    metered: bool
    engine: str | None = None
    bytes: int | None = None
    # BigQuery on-demand list price; None where the engine bills time.
    est_cost_usd: float | None = None
    basis: str | None = None
    max_bytes_billed: int | None = None
    exceeds_cap: bool = False

from dte.api.deps import (
    get_connection_store,
    get_current_user,
    get_destination_store,
    get_eval_set_store,
    get_lookup_table_store,
    get_pipeline_revision_store,
    get_pipeline_store,
    get_run_event_store,
    get_run_store,
    get_source_store,
)
from dte.api.interactive import SAMPLE_ROWS, run_interactive
from dte.compiler.dialect_notes import (
    SOURCE_DIALECT,
    execution_dialect_of,
    notes_for,
    raw_sql_fragment,
    transpile_fragment,
)
from dte.compiler.ibis_compiler import compile_pipeline
from dte.compiler.interpolate import (
    InterpolationError,
    ParamValidationError,
    interpolate_pipeline,
    resolve_context,
)
from dte.engine.backend_registry import BackendRegistry
from dte.engine.duckdb_engine import DuckDBEngine
from dte.logging import decrypt_context_var, get_logger
from dte.models.pipeline import (
    ALLOWED_OPS,
    Connection,
    Destination,
    LookupTable,
    Pipeline,
    PipelineBase,
    PipelineNotification,
    PipelineRevisionBase,
    PipelineSchedule,
    Source,
    SourceTableRef,
    coerce_source_refs,
    pipeline_requires_output,
)
from dte.models.user import User
from dte.pipelines.diff import diff_pipeline, summarise_diff
from dte.security.permissions import requires
from dte.sources import metered
from dte.sources.loader import load_source
from dte.sources.sample import load_interactive, sample_info
from dte.store.base import (
    ConnectionStore,
    DestinationStore,
    EvalSetStore,
    LookupTableStore,
    PipelineRevisionStore,
    PipelineStore,
    RunEventStore,
    RunStore,
    SourceStore,
)

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
    # Sweep/promote/as-eval pass a copied table row; its timestamps aren't spec.
    new_config = pipeline.model_dump(mode="json", exclude={"created_at", "updated_at"})
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


async def _validate_pipeline_refs(
    pipeline: PipelineBase,
    s_store: SourceStore,
    d_store: DestinationStore,
):
    """Raise 422 if any source id or the destination id doesn't exist, if
    an alias is duplicated/malformed, if `table` is missing for a
    `sql_database` ref (or set for any other kind), or if a join step's
    `left`/`right` doesn't resolve to a declared alias or an earlier
    step's `output_id`."""
    refs = coerce_source_refs(pipeline.sources)
    missing_sources: list[str] = []
    duplicate_aliases: set[str] = set()
    table_errors: list[str] = []
    seen_aliases: set[str] = set()
    known_keys: set[str] = set()
    for ref in refs:
        if ref.alias in seen_aliases:
            duplicate_aliases.add(ref.alias)
        seen_aliases.add(ref.alias)
        known_keys.add(ref.alias)
        source = await s_store.get(ref.source_id)
        if not source:
            missing_sources.append(ref.source_id)
            continue
        if source.source_type == "sql_database" and not ref.table:
            table_errors.append(
                f"alias {ref.alias!r}: 'table' is required for sql_database source '{ref.source_id}'"
            )
        elif source.source_type != "sql_database" and ref.table:
            table_errors.append(
                f"alias {ref.alias!r}: 'table' is not allowed for "
                f"{source.source_type!r} source '{ref.source_id}'"
            )

    join_errors: list[str] = []
    for i, step in enumerate(pipeline.steps or []):
        if not isinstance(step, dict) or step.get("op") != "join":
            continue
        for side in ("left", "right"):
            operand = step.get(side)
            if operand not in known_keys:
                join_errors.append(
                    f"steps[{i}].{side}: unknown operand {operand!r} — must be "
                    f"a declared source alias or an earlier step's output_id"
                )
        output_id = step.get("output_id")
        if isinstance(output_id, str):
            known_keys.add(output_id)

    # Quality, eval and viz pipelines all write nowhere, so none requires a
    # destination. Without this an eval pipeline is rejected at save for a
    # missing `output_id` it is never supposed to have.
    needs_output = pipeline_requires_output(pipeline)
    missing_dest = None
    if needs_output:
        missing_dest = None if await d_store.get(pipeline.output_id) else pipeline.output_id
    if missing_sources or missing_dest or duplicate_aliases or table_errors or join_errors:
        detail: dict = {}
        if missing_sources:
            detail["missing_sources"] = missing_sources
        if missing_dest:
            detail["missing_destination"] = missing_dest
        if duplicate_aliases:
            detail["duplicate_aliases"] = sorted(duplicate_aliases)
        if table_errors:
            detail["table_errors"] = table_errors
        if join_errors:
            detail["join_errors"] = join_errors
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
    for ref in coerce_source_refs(pipeline.sources):
        source = await s_store.get(ref.source_id)
        if not source:
            continue  # already caught by _validate_pipeline_refs
        conn = await c_store.get(source.connection_id)
        if not conn:
            raise HTTPException(
                status_code=422,
                detail=f"Source '{ref.source_id}' references missing connection '{source.connection_id}'",
            )
        src_types.append((ref.source_id, conn.connection_type))

    # Quality, eval and viz pipelines all write nowhere, so none requires a
    # destination. Without this an eval pipeline is rejected at save for a
    # missing `output_id` it is never supposed to have.
    needs_output = pipeline_requires_output(pipeline)
    dest_tuple: tuple[str, str] | None = None
    if needs_output:
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


@router.get("/allowed-ops", dependencies=[Depends(requires("pipeline:read"))])
async def allowed_ops() -> dict[str, list[str]]:
    """Which step ops each pipeline type may hold — the builder's Add-step
    menu reads this, so it offers exactly what save accepts."""
    return {k: sorted(v) for k, v in ALLOWED_OPS.items()}


@router.post("/pipelines", dependencies=[Depends(requires("pipeline:write"))])
async def create_pipeline(
    pipeline: PipelineBase,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
    user: User = Depends(get_current_user),
    es_store: EvalSetStore = Depends(get_eval_set_store),
):
    from dte.api.routes.notifications import validate_notifications
    from dte.api.routes.schedules import validate_schedule

    await _validate_pipeline_refs(pipeline, s_store, d_store)
    await _validate_engine_compat(pipeline, s_store, d_store, c_store)
    await validate_schedule(pipeline, es_store, d_store)
    await validate_notifications(pipeline.notifications)
    try:
        await store.save(Pipeline(**pipeline.model_dump()))
    except ValueError as e:  # name collision on UNIQUE(name)
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
    es_store: EvalSetStore = Depends(get_eval_set_store),
) -> Pipeline:
    from dte.api.routes.notifications import validate_notifications
    from dte.api.routes.schedules import validate_schedule

    if pipeline.id != pipeline_id:
        raise HTTPException(status_code=400, detail="Pipeline id in path and body must match")
    existing = await store.get(pipeline_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    # A body that doesn't mention the schedule (the builder saving steps)
    # keeps it; an explicit `null` removes it.
    if "schedule" not in pipeline.model_fields_set and existing.schedule:
        pipeline.schedule = PipelineSchedule.model_validate(existing.schedule)
    if "notifications" not in pipeline.model_fields_set:
        pipeline.notifications = [PipelineNotification.model_validate(n) for n in existing.notifications or []]
    await _validate_pipeline_refs(pipeline, s_store, d_store)
    await _validate_engine_compat(pipeline, s_store, d_store, c_store)
    await validate_schedule(pipeline, es_store, d_store)
    await validate_notifications(pipeline.notifications)
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
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
    user: User = Depends(get_current_user),
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
    for ref in coerce_source_refs(getattr(source, "sources", None) or []):
        row = await s_store.get(ref.source_id)
        if row is not None:
            kinds[ref.source_id] = row.source_type
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
    await _record_revision(twin, rev_store, user)
    response.status_code = 201
    return {"pipeline_id": twin_id, "created": True}


@router.get(
    "/pipelines/{pipeline_id}/comparisons",
    dependencies=[Depends(requires("eval:read"))],
)
async def list_pipeline_comparisons(
    pipeline_id: str,
    limit: int = Query(20, ge=1, le=100),
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
):
    """Comparisons already run for this pipeline, newest first.

    The compare page shipped reachable only from the redirect fired once at
    launch — navigate away and the comparison was gone unless you had kept
    the URL. That is the same "reachable from nowhere" failure this plan was
    written to fix elsewhere.

    Two details, both consequences of the variant namespace:

    A sweep's runs are filed under the *cells* it created, never under the
    pipeline that was swept, so the obvious lookup by `pipeline_id` returns
    nothing at all.

    Asking from a cell answers for the root. Someone who followed a link to
    a variant must see the same history, not an empty page implying nothing
    was ever compared.
    """
    from dte.evals.sweep import root_pipeline_id

    if await p_store.get(pipeline_id) is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    root = root_pipeline_id(pipeline_id)

    runs = await r_store.list_sweep_runs_for_root(root)
    grouped: dict[str, dict] = {}
    for run in runs:
        sweep_id = run.get("sweep_id")
        if not sweep_id:
            continue
        entry = grouped.setdefault(sweep_id, {
            "sweep_id": sweep_id,
            "eval_set_id": run.get("eval_set_id"),
            "started_at": run.get("started_at"),
            "cells": 0,
            "pending": 0,
            # None, never 0.0 — an unlabelled comparison is the normal case
            # in this flow, and zero would read as "every config failed".
            "best_macro_f1": None,
        })
        entry["cells"] += 1
        if run.get("status") in ("pending", "running"):
            entry["pending"] += 1
        f1 = (run.get("scores") or {}).get("macro_f1")
        if f1 is not None:
            best = entry["best_macro_f1"]
            entry["best_macro_f1"] = f1 if best is None else max(best, f1)
        # Runs arrive newest-first; the comparison is as old as its first cell.
        started = run.get("started_at")
        if started and (entry["started_at"] is None or started > entry["started_at"]):
            entry["started_at"] = started

    return {
        "pipeline_id": root,
        "comparisons": list(grouped.values())[:limit],
    }


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
) -> tuple[list[tuple[SourceTableRef, Source, Connection, dict]], tuple[Destination, dict]]:
    """Resolve pipeline id refs to (SourceTableRef, Source, Connection,
    credentials) tuples and (Destination, credentials). Missing anything →
    422 naming what's gone."""
    sources: list[tuple[SourceTableRef, Source, Connection, dict]] = []
    for ref in coerce_source_refs(pipeline.sources):
        source = await s_store.get(ref.source_id)
        if not source:
            raise HTTPException(status_code=422, detail=f"Source not found: {ref.source_id}")
        conn = await c_store.get(source.connection_id)
        if not conn:
            raise HTTPException(
                status_code=422,
                detail=f"Source '{ref.source_id}' references missing connection '{source.connection_id}'",
            )
        sources.append((ref, source, conn, conn.credentials))

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
) -> list[tuple[SourceTableRef, Source, Connection, dict]]:
    """Resolve only sources (no destination) — used for quality pipelines."""
    sources: list[tuple[SourceTableRef, Source, Connection, dict]] = []
    for ref in coerce_source_refs(pipeline.sources):
        source = await s_store.get(ref.source_id)
        if not source:
            raise HTTPException(status_code=422, detail=f"Source not found: {ref.source_id}")
        conn = await c_store.get(source.connection_id)
        if not conn:
            raise HTTPException(
                status_code=422,
                detail=f"Source '{ref.source_id}' references missing connection '{source.connection_id}'",
            )
        sources.append((ref, source, conn, conn.credentials))
    return sources


def _load_compile(
    pipeline: Pipeline,
    sources,
    destination,
    lookups,
    *,
    sample: int | None = None,
    on_tables=None,
    live: bool = False,
    **callbacks,
) -> dict | None:
    """Load sources, compile, and with `sample` execute that many rows.

    Sync, and owns the DuckDB connection from creation to last read — call it
    through `run_interactive` (plan 084), never inline in a route. A load or
    compile failure raises; an execution failure is the returned `error`,
    matching what the preview body has always reported.

    `live` skips the cached samples and reads every source the way a run
    does — on a metered source that is a billed query (plan 093).
    """
    engine = DuckDBEngine()
    registry = BackendRegistry(duckdb_con=engine.con)
    tables = {
        ref.alias: (load_source(s, registry, conn, creds, table=ref.table) if live else
                    load_interactive(s, registry, conn, creds, table=ref.table, sample=SAMPLE_ROWS))
        for ref, s, conn, creds in sources
    }
    # Fired before compilation, so a caller still learns which backend
    # the pipeline runs on when a later step fails to compile — that is
    # exactly when the editor most needs to explain itself.
    if on_tables is not None:
        on_tables(tables)
    compiled = compile_pipeline(
        pipeline, tables,
        output=destination.config if destination else None,
        lookup_tables=lookups, engine=engine, **callbacks,
    )
    if sample is None:
        return None
    out: dict = {"rows": [], "final_sql": None, "error": None, "samples": [] if live else _samples(sources)}
    try:
        out["final_sql"] = str(ibis.to_sql(compiled.limit(sample), dialect=getattr(engine, "dialect", "duckdb")))
    except Exception:
        pass
    try:
        df = compiled.limit(sample).execute()
        out["rows"] = json.loads(df.to_json(orient="records", date_format="iso"))
    except Exception as e:
        out["error"] = metered.cap_message(e) or str(e)
    return out


def _samples(sources) -> list[dict]:
    """Which sources this preview read from a cached sample, and how old it is."""
    out = []
    for ref, s, conn, _ in sources:
        info = sample_info(s, conn, ref.table)
        if info:
            out.append({"alias": ref.alias, "source_id": s.id, "table": ref.table,
                        "rows": info["rows"], "taken_at": info["taken_at"]})
    return out


# Ops that execute while compiling. Pricing a pipeline with one would run it.
_EAGER_OPS = frozenset({"extract", "structure", "pivot", "check", "profile"})


def _estimate(pipeline, sources, destination, lookups) -> PipelineEstimate:
    """What a run would scan on its metered sources, without running anything
    billable. Sync — call through `run_interactive`.

    Compiles against the live backends (metadata calls only) and prices the
    compiled query when it runs on the warehouse, so filters and projections
    count. Otherwise (mixed sources, an eager step) each metered table is
    priced in full: the run would pull all of it.
    """
    meters = [(ref, s, conn, creds) for ref, s, conn, creds in sources if metered.is_metered(s, conn)]
    if not meters:
        return PipelineEstimate(metered=False)
    engine = DuckDBEngine()
    registry = BackendRegistry(duckdb_con=engine.con)
    tables = {
        ref.alias: (load_source(s, registry, conn, creds, table=ref.table) if metered.is_metered(s, conn)
                    else load_interactive(s, registry, conn, creds, table=ref.table, sample=SAMPLE_ROWS))
        for ref, s, conn, creds in sources
    }
    conn_of = {id(registry.for_connection(conn, creds)): conn for _, _, conn, creds in meters}
    targets, basis = [], "compiled query (dry run)"
    if not any((st or {}).get("op") in _EAGER_OPS for st in pipeline.steps or []):
        compiled = compile_pipeline(pipeline, tables, output=destination.config if destination else None,
                                    lookup_tables=lookups, engine=engine)
        try:
            backend = compiled._find_backend()
        except Exception:  # spans backends: priced per table below
            backend = None
        if id(backend) in conn_of:
            targets = [(backend, conn_of[id(backend)], compiled)]
    if not targets:
        basis = "full scan of each warehouse table"
        targets = [(registry.for_connection(conn, creds), conn, tables[ref.alias])
                   for ref, _, conn, creds in meters]
    total, usd = 0, None
    for backend, conn, expr in targets:
        kind = conn.connection_type
        n = metered.estimate_bytes(backend, kind, str(ibis.to_sql(expr)))
        if n is None:
            continue
        total += n
        if (c := metered.est_cost_usd(kind, n)) is not None:
            usd = (usd or 0) + c
    caps = [conn.credentials.get("max_bytes_billed") for _, _, conn, _ in meters]
    cap = min((int(c) for c in caps if c), default=None)
    return PipelineEstimate(
        metered=True, engine=meters[0][2].connection_type, bytes=total, est_cost_usd=usd,
        basis=basis, max_bytes_billed=cap, exceeds_cap=cap is not None and total > cap,
    )


async def _compile_body_pipeline(
    body: PipelineBase,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
    lt_store: LookupTableStore,
    *,
    on_step_schema=None,
    on_step_sql=None,
    on_step=None,
    on_tables=None,
    params: dict[str, str] | None = None,
    sample: int | None = None,
    live: bool = False,
) -> dict | None:
    """Shared plumbing for endpoints that compile an unsaved pipeline body.

    Resolves source/destination/connection/lookup refs from the given
    body, then loads, compiles and (with `sample`) executes in a thread via
    `_load_compile`, whose result it returns.
    Compile errors bubble up as `HTTPException(422, str(e))`.

    `on_step_schema` is forwarded to :func:`compile_pipeline` (plan 038
    item 7).
    """
    # Cast the PipelineBase body to Pipeline so downstream code that expects
    # `.sources`, `.output_id`, `.steps` all works — validators already fired.
    pipeline = Pipeline(**body.model_dump())
    decrypt_context_var.set("pipeline_dry_run")
    # Quality, eval and viz pipelines all write nowhere, so none requires a
    # destination. Without this an eval pipeline is rejected at save for a
    # missing `output_id` it is never supposed to have.
    needs_output = pipeline_requires_output(pipeline)
    try:
        pipeline = interpolate_pipeline(pipeline, resolve_context(pipeline, params))
        if not needs_output:
            sources = await _resolve_sources(pipeline, s_store, c_store)
            destination = None
        else:
            sources, (destination, _) = await _resolve(pipeline, s_store, d_store, c_store)
        lookups = await _resolve_lookups(pipeline, lt_store)
        return await run_interactive(
            _load_compile, pipeline, sources, destination, lookups,
            sample=sample, on_tables=on_tables, on_step_schema=on_step_schema,
            on_step_sql=on_step_sql, on_step=on_step, live=live,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


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

    # The step being applied when compilation blew up. Without it a bad
    # expression in step 2 renders as one unattributed error at the bottom
    # of the preview pane, reading as "the pipeline is broken".
    failed_step: list[int | None] = [None]

    def _capture_step(idx: int, op: str, status: str, msg=None):
        if status == "failed":
            failed_step[0] = idx

    dialect: list[str] = [SOURCE_DIALECT]

    def _capture_dialect(tables: dict):
        first = next(iter(tables.values()), None)
        if first is not None:
            dialect[0] = execution_dialect_of(first)

    # A partially-configured pipeline (e.g. aggregate with no aggregations yet)
    # will 422 mid-compile. We still want to return the schemas captured up to
    # the failing step so downstream editors see fresh columns from earlier
    # steps the user just edited — otherwise field autocomplete stays stuck
    # on stale results until the whole pipeline compiles cleanly.
    error: str | None = None
    try:
        await _compile_body_pipeline(
            body, s_store, d_store, c_store, lt_store, on_step_schema=_capture,
            on_step=_capture_step, on_tables=_capture_dialect,
        )
    except HTTPException as e:
        error = str(e.detail)

    # Dialect feedback (plan 062). Pure functions of (step, dialect), so they
    # are computed for every raw-SQL step whether or not the pipeline
    # compiled — the readback must survive the error it is explaining.
    expr_sql: dict[int, str] = {}
    warnings: list[dict] = []
    for idx, step in enumerate(body.steps or []):
        fragment = raw_sql_fragment(step)
        if fragment is None:
            continue
        transpiled = transpile_fragment(fragment, dialect[0])
        if transpiled is not None:
            expr_sql[idx] = transpiled
        for note in notes_for(fragment, dialect[0]):
            warnings.append({"step": idx, "code": note.code, "message": note.message})

    # JSON keys are strings; matches how the frontend will look them up.
    return {
        "step_schemas": {str(k): v for k, v in schemas.items()},
        "error": error,
        "error_step": failed_step[0],
        "dialect": dialect[0],
        "step_expr_sql": {str(k): v for k, v in expr_sql.items()},
        "warnings": warnings,
    }


@router.post("/pipelines/dry-run", dependencies=[Depends(requires("pipeline:read"))])
async def dry_run_pipeline(
    body: PipelineBase,
    limit: int = 20,
    params: str | None = None,
    live: bool = False,
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
    sampled: dict = {}
    try:
        parsed_params = _parse_params_query(params)
    except HTTPException as e:
        error = str(e.detail)
        parsed_params = None
    if error is None:
        try:
            sampled = await _compile_body_pipeline(
                body, s_store, d_store, c_store, lt_store,
                on_step_sql=_capture_sql,
                params=parsed_params,
                sample=limit,
                live=live,
            )
            error = sampled["error"]
        except HTTPException as e:
            error = str(e.detail)

    rows: list = sampled.get("rows", [])
    final_sql: str | None = sampled.get("final_sql")

    return {
        "rows": rows,
        "count": len(rows),
        "step_sqls": {str(k): v for k, v in step_sqls.items()},
        "final_sql": final_sql,
        "error": error,
        "samples": sampled.get("samples", []),
    }


@router.get("/pipelines/{pipeline_id}/preview", dependencies=[Depends(requires("pipeline:read"))])
async def preview_pipeline(
    pipeline_id: str,
    limit: int = 100,
    params: str | None = None,
    live: bool = False,
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

    # Quality, eval and viz pipelines all write nowhere, so none requires a
    # destination. Without this an eval pipeline is rejected at save for a
    # missing `output_id` it is never supposed to have.
    needs_output = pipeline_requires_output(pipeline)
    error: str | None = None
    sampled: dict = {}
    try:
        parsed_params = _parse_params_query(params)
        pipeline = interpolate_pipeline(pipeline, resolve_context(pipeline, parsed_params))
        if not needs_output:
            sources = await _resolve_sources(pipeline, s_store, c_store)
            destination = None
        else:
            sources, (destination, _) = await _resolve(pipeline, s_store, d_store, c_store)
        lookups = await _resolve_lookups(pipeline, lt_store)
        # Preview runs against whichever backend each source resolves to
        # (postgres source → postgres pushdown). DuckDBEngine here is just
        # the writer glue + raw-SQL rejection helper; the actual per-source
        # execution locus is picked by BackendRegistry.
        sampled = await run_interactive(
            _load_compile, pipeline, sources, destination, lookups,
            sample=limit, on_step_sql=_capture_sql, live=live,
        )
        error = sampled["error"]
    except HTTPException:
        raise
    except Exception as e:
        error = str(e)

    rows: list = sampled.get("rows", [])
    final_sql: str | None = sampled.get("final_sql")

    return {
        "rows": rows,
        "count": len(rows),
        "step_sqls": {str(k): v for k, v in step_sqls.items()},
        "final_sql": final_sql,
        "error": error,
        "samples": sampled.get("samples", []),
    }


async def validate_eval_corpus_match(pipeline, eval_set_id: str, es_store) -> None:
    """The pipeline must read the corpus its labels describe.

    Labels join by `doc_key` (sha256 of the document), so a pipeline
    pointed at a different documents source produces hashes that match
    nothing: the run completes green having scored zero documents, which
    reads as a broken extractor rather than a mismatched corpus.

    Presence, not exclusivity — a pipeline may carry other sources
    alongside the corpus and still be scoring the right documents.

    Shared by `trigger_pipeline` and the sweep launcher. The sweep used to
    skip it, which was survivable while a sweep was a side door; now that
    it is the primary path into scoring, a mismatch is inherited by every
    cell of the matrix and billed for on each one.
    """
    eval_set = await es_store.get(eval_set_id)
    if eval_set is None:
        raise HTTPException(status_code=422, detail=f"eval set not found: {eval_set_id}")
    refs = coerce_source_refs(getattr(pipeline, "sources", None) or [])
    source_ids = [r.source_id for r in refs]
    if eval_set.source_id not in source_ids:
        raise HTTPException(
            status_code=422,
            detail=(
                f"eval set '{eval_set_id}' labels documents from source "
                f"'{eval_set.source_id}', but pipeline '{pipeline.id}' reads "
                f"{source_ids}. Scoring these together would match no "
                f"labels and report zero."
            ),
        )


async def start_eval_run(
    pipeline_id: str,
    *,
    eval_set_id: str,
    revision_id: str,
    sweep_id: str | None = None,
    **_unused,
) -> str:
    """Start one eval run (an Airflow dag run) of `revision_id` and return its
    run id. The sweep launcher comes through here."""
    from dte.airflow.trigger import trigger_dag_run

    conf = {"eval_set_id": eval_set_id, "revision_id": revision_id}
    if sweep_id:
        conf["sweep_id"] = sweep_id
    return await trigger_dag_run(pipeline_id, conf, wait=120)


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
    sampled = await run_interactive(_load_compile, pipeline, sources, None, lookups, sample=limit)
    if sampled["error"]:
        raise RuntimeError(sampled["error"])
    return sampled["rows"]


@router.post("/pipelines/estimate", response_model=PipelineEstimate, dependencies=[Depends(requires("pipeline:read"))])
async def estimate_pipeline(
    body: PipelineBase,
    params: str | None = None,
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
):
    """What a run (or a live preview) of this unsaved body would scan on its
    metered sources (plan 093). Free: BigQuery dry run, Snowflake EXPLAIN."""
    pipeline = Pipeline(**body.model_dump())
    try:
        pipeline = interpolate_pipeline(pipeline, resolve_context(pipeline, _parse_params_query(params)))
        if pipeline_requires_output(pipeline):
            sources, (destination, _) = await _resolve(pipeline, s_store, d_store, c_store)
        else:
            sources, destination = await _resolve_sources(pipeline, s_store, c_store), None
        lookups = await _resolve_lookups(pipeline, lt_store)
        return await run_interactive(_estimate, pipeline, sources, destination, lookups)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/pipelines/{pipeline_id}/trigger", dependencies=[Depends(requires("pipeline:trigger"))])
async def trigger_pipeline(
    pipeline_id: str,
    body: TriggerRequest | None = None,
    p_store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
    es_store: EvalSetStore = Depends(get_eval_set_store),
):
    """Validate, then start an Airflow dag run of `dte__<pipeline_id>`."""
    from dte.airflow.trigger import trigger_dag_run

    pipeline = await p_store.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    # Fail fast on missing refs before creating a run.
    decrypt_context_var.set("pipeline_run")
    _ptype = getattr(pipeline, "pipeline_type", "transform") or "transform"
    destination = None
    if _ptype in ("quality", "eval"):
        sources = await _resolve_sources(pipeline, s_store, c_store)
    else:
        sources, (destination, _) = await _resolve(pipeline, s_store, d_store, c_store)

    # An eval run with no corpus would score nothing — reject at trigger.
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
        await validate_eval_corpus_match(pipeline, eval_set_id, es_store)
    lookups = await _resolve_lookups(pipeline, lt_store)
    await _validate_engine_compat(pipeline, s_store, d_store, c_store)
    user_params = (body.params if body else {}) or {}
    # Resolve the context up-front so `now`/`today` snapshot at trigger time
    # and bad params / unknown vars fail here instead of inside the task.
    try:
        run_context = resolve_context(pipeline, user_params)
        resolved = interpolate_pipeline(pipeline, run_context)
    except ParamValidationError as e:
        raise HTTPException(status_code=422, detail=e.payload())
    except InterpolationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not (body and body.confirm) and any(metered.is_metered(s, c) for _, s, c, _ in sources):
        # Nothing starts until the caller has seen what it will scan.
        try:
            estimate = await run_interactive(_estimate, resolved, sources, destination, lookups)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"could not estimate this run: {e}") from e
        return {"estimate": estimate.model_dump(), "enqueued": False}
    latest_rev = await rev_store.latest_for_pipeline(pipeline_id)

    conf = {"params": user_params, "context": run_context}
    if latest_rev:
        conf["revision_id"] = latest_rev.id
    if eval_set_id:
        conf["eval_set_id"] = eval_set_id
    if sweep_id:
        conf["sweep_id"] = sweep_id
    # A pipeline saved seconds ago may not be a DAG yet; wait for the parse.
    return {"run_id": await trigger_dag_run(pipeline_id, conf, wait=60)}


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
    """Mark the Airflow dag run failed; Airflow stops its running task."""
    from dte.airflow.trigger import cancel_dag_run, dag_id_for

    run = await r_store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"Run is already {run.get('status')}")
    return {"cancelled": await cancel_dag_run(dag_id_for(run["pipeline_id"]), run_id)}
