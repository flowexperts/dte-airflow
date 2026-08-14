"""Eval harness API (plan 051 task 9).

Eval-set and example CRUD, label import, the leaderboard, per-field failure
drill-down, and the sweep launcher.

Two things here are guardrails rather than features, and both exist because
the failure they prevent is silent:

**Every label write bumps `labels_version`.** Runs pin the version they scored
against, so the leaderboard can grey out and de-rank runs whose labels have
since changed. Without it, editing one label silently invalidates every
historical comparison while the numbers keep rendering as if nothing happened.

**The sweep launcher will not enqueue without confirmation.** `POST /sweep`
with `confirm=false` (the default) returns an estimate and enqueues nothing.
A cartesian product of providers x models x prompts over a few hundred
documents is real money, and a launcher that spends it on a mis-click is a
launcher people stop using.
"""
from __future__ import annotations

import csv
import io
import itertools
import json
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from dte.api.deps import (
    get_connection_store,
    get_eval_example_store,
    get_eval_set_store,
    get_lookup_table_store,
    get_pipeline_store,
    get_destination_store,
    get_run_event_store,
    get_run_store,
    get_schedule_store,
    get_source_store,
)
from dte.api.routes.pipelines import (
    materialise_pipeline_rows,
    start_eval_run,
    validate_eval_corpus_match,
)
from dte.config import get_settings
from dte.evals.bootstrap import CONSENSUS_LABEL_SOURCE, consensus
from dte.evals.comparison import build_comparison
from dte.evals.derive import eval_set_fingerprint, field_specs_from_structure
from dte.evals.runner import collapse_rows_by_doc
from dte.evals.scoring import intervals_overlap
from dte.evals.digest import config_digest
from dte.evals.sweep import (
    apply_cell,
    detached_copy,
    root_pipeline_id,
    variant_id,
    variant_name,
)
from dte.models.eval import EvalExampleBase, EvalSetBase
from dte.security.permissions import requires
from dte.store.base import EvalExampleStore, EvalSetStore, PipelineStore, RunStore

router = APIRouter()

# Hard stop on a runaway matrix. A 5x4x3 sweep over 500 documents is 30k model
# calls; the cap is what stops a typo in the matrix from becoming an invoice.
DEFAULT_MAX_SWEEP_CELLS = 50


# ── eval sets ────────────────────────────────────────────────────────────


async def _validate_source(source_id: str, s_store) -> None:
    """An eval set's corpus must be a real `documents` source.

    Neither mistake announces itself later. A missing id fails at trigger,
    naming a pipeline the user wasn't editing. A source of the wrong kind is
    worse: it runs, produces rows carrying no `artifact_ref`, joins against
    zero labels, and scores a flat zero — which reads as a broken extractor
    and can burn a whole sweep before anyone suspects the set itself.

    Both are knowable here, so both are refused here.
    """
    source = await s_store.get(source_id)
    if not source:
        raise HTTPException(
            status_code=422,
            detail=(
                f"source '{source_id}' does not exist — an eval set scores "
                f"against a corpus, so it needs a saved documents source"
            ),
        )
    if source.source_type != "documents":
        raise HTTPException(
            status_code=422,
            detail=(
                f"source '{source_id}' is a {source.source_type!r} source, but an "
                f"eval set needs a 'documents' source. Labels join to extracted "
                f"rows by document hash, which only a documents source produces; "
                f"any other kind would score zero on every field with no error."
            ),
        )


@router.post("/eval-sets", status_code=201, dependencies=[Depends(requires("eval:write"))])
async def create_eval_set(
    eval_set: EvalSetBase,
    store: EvalSetStore = Depends(get_eval_set_store),
    s_store=Depends(get_source_store),
):
    if await store.get(eval_set.id):
        raise HTTPException(status_code=409, detail=f"Eval set '{eval_set.id}' already exists")
    await _validate_source(eval_set.source_id, s_store)
    await store.save(eval_set)
    return eval_set.model_dump()


class ForPipelineRequest(BaseModel):
    """Derive the eval set a pipeline implies, or find the one it already has."""

    pipeline_id: str


@router.post("/eval-sets:for-pipeline", dependencies=[Depends(requires("eval:write"))])
async def eval_set_for_pipeline(
    body: ForPipelineRequest,
    response: Response,
    store: EvalSetStore = Depends(get_eval_set_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
    s_store=Depends(get_source_store),
):
    """The eval set implied by a pipeline's structure step and corpus.

    Plan 051 made the user type their field list twice — once in the
    structure step, once in `field_specs` — under a builder warning that a
    mismatch "won't error; it scores zero on every document." That warning
    is the design confessing. The pipeline already declares the fields, so
    the set is derived from it and the two cannot drift.

    The id is `<source>__<fingerprint>` and the fingerprint covers exactly
    what changes the meaning of a score: field names, comparator types, and
    comparator options. Not order, not descriptions — those are edits people
    make constantly while iterating on a prompt, and minting a fresh set for
    them would silently discard every label collected so far.

    Consequently two pipelines extracting the same fields from the same
    corpus land on one set, which is the whole point: claude and openai
    scored against different sets would never appear on one leaderboard.
    """
    pipeline = await p_store.get(body.pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    step = next(
        (s for s in (getattr(pipeline, "steps", None) or [])
         if isinstance(s, dict) and s.get("op") == "structure"),
        None,
    )
    if step is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "an eval set scores the fields a structure step declares, and "
                f"pipeline '{body.pipeline_id}' has no structure step"
            ),
        )

    source_id = None
    for sid in getattr(pipeline, "sources", None) or []:
        row = await s_store.get(sid)
        if row is not None and row.source_type == "documents":
            source_id = sid
            break
    if source_id is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"pipeline '{body.pipeline_id}' reads no 'documents' source. "
                "Labels are keyed by document hash and no other source kind "
                "produces one, so there is nothing to score against."
            ),
        )

    try:
        specs = field_specs_from_structure(step)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    set_id = f"{source_id}__{eval_set_fingerprint(source_id, specs)}"
    existing = await store.get(set_id)
    if existing is not None:
        return {"eval_set_id": set_id, "created": False, "labels_version": existing.labels_version}

    await store.save(EvalSetBase(
        id=set_id,
        name=f"{pipeline.name} — {len(specs)} field{'' if len(specs) == 1 else 's'}",
        source_id=source_id,
        field_specs=specs,
    ))
    response.status_code = 201
    return {"eval_set_id": set_id, "created": True, "labels_version": 1}


@router.get("/eval-sets", dependencies=[Depends(requires("eval:read"))])
async def list_eval_sets(
    limit: int = 50,
    offset: int = 0,
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
    r_store: RunStore = Depends(get_run_store),
):
    rows = await store.list(limit=limit, offset=offset)
    out = []
    for r in rows:
        d = r.model_dump()
        d["example_count"] = await ex_store.count_for_set(r.id)
        d["label_sources"] = await ex_store.count_by_label_source(r.id)
        best, last = await _best_and_last(r_store, r.id, r.labels_version)
        # Null, not zero: a set nobody has run and a set scoring zero are
        # opposite situations, and rendering them alike is how a broken
        # extractor hides on an index page.
        d["best_macro_f1"] = best
        d["last_run_at"] = last
        out.append(d)
    return out


async def _best_and_last(r_store, eval_set_id: str, labels_version: int):
    """Best current score and most recent activity for one set.

    "Current" excludes runs pinned to a superseded `labels_version`, the
    same rule the leaderboard uses to grey them out. A 0.99 earned against
    labels that have since been corrected is not this set's best, and
    showing it would put a number on the list that the detail page
    contradicts.
    """
    runs = await r_store.list_for_eval_set(eval_set_id, limit=200)
    best = None
    last = None
    for run in runs:
        started = run.get("started_at")
        if started and (last is None or str(started) > str(last)):
            last = started
        if run.get("labels_version") != labels_version:
            continue
        score = (run.get("scores") or {}).get("macro_f1")
        if score is not None and (best is None or score > best):
            best = score
    return best, last


@router.get("/eval-sets/{eval_set_id}", dependencies=[Depends(requires("eval:read"))])
async def get_eval_set(
    eval_set_id: str,
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
):
    row = await store.get(eval_set_id)
    if not row:
        raise HTTPException(status_code=404, detail="Eval set not found")
    d = row.model_dump()
    d["example_count"] = await ex_store.count_for_set(eval_set_id)
    d["holdout_count"] = await ex_store.count_for_set(eval_set_id, split="holdout")
    d["label_sources"] = await ex_store.count_by_label_source(eval_set_id)
    d["judge_labeled_warning"] = _judge_warning(d["label_sources"])
    return d


def _judge_warning(label_sources: dict[str, int]) -> str | None:
    """Warn when a set is majority judge-labeled.

    Above that line you are substantially scoring models against a model, and
    the number on the leaderboard measures agreement rather than correctness.
    Surfaced rather than silently mixed in, because the scores look *better*
    when this is happening, not worse.
    """
    total = sum(label_sources.values())
    judge = label_sources.get("judge", 0)
    if total and judge / total > 0.5:
        pct = round(100 * judge / total)
        return (
            f"{pct}% of these labels came from an LLM judge — this score partly "
            "measures agreement with a model, not correctness"
        )
    return None


@router.put("/eval-sets/{eval_set_id}", dependencies=[Depends(requires("eval:write"))])
async def update_eval_set(
    eval_set_id: str,
    eval_set: EvalSetBase,
    store: EvalSetStore = Depends(get_eval_set_store),
    s_store=Depends(get_source_store),
):
    existing = await store.get(eval_set_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Eval set not found")
    # A set can be repointed after creation, so the rule has to hold here too
    # or it is a speed bump rather than a guarantee.
    await _validate_source(eval_set.source_id, s_store)
    eval_set.id = eval_set_id
    await store.save(eval_set)
    return (await store.get(eval_set_id)).model_dump()


@router.delete("/eval-sets/{eval_set_id}", status_code=204, dependencies=[Depends(requires("eval:delete"))])
async def delete_eval_set(
    eval_set_id: str,
    store: EvalSetStore = Depends(get_eval_set_store),
    sch_store=Depends(get_schedule_store),
):
    # Same contract as sources and destinations: refuse and name the
    # referrers. Cascading would silently delete a schedule the user built
    # separately, and orphaning would leave one that fires nightly and
    # fails every time — a broken thing that reports itself as a run
    # failure rather than as the deletion that actually caused it.
    referencing = await sch_store.list_for_eval_set(eval_set_id)
    if referencing:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "eval_set_in_use",
                "message": "This eval set is scheduled. Delete or repoint "
                           "the schedules first.",
                "referenced_by": {"schedules": [s.id for s in referencing]},
            },
        )
    if not await store.delete(eval_set_id):
        raise HTTPException(status_code=404, detail="Eval set not found")
    return None


# ── examples (labels) ────────────────────────────────────────────────────


class ExampleWrite(BaseModel):
    """One label write. `id` is server-generated; identity is the document."""

    doc_key: str
    doc_ref: str | None = None
    labels: dict = Field(default_factory=dict)
    label_source: str = "human"
    split: str = "train"


@router.post(
    "/eval-sets/{eval_set_id}/examples",
    status_code=201,
    dependencies=[Depends(requires("eval:write"))],
)
async def upsert_example(
    eval_set_id: str,
    body: ExampleWrite,
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
):
    eval_set = await store.get(eval_set_id)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")

    _reject_unknown_fields(eval_set, body.labels)
    try:
        example = EvalExampleBase(
            id="",
            eval_set_id=eval_set_id,
            doc_key=body.doc_key,
            doc_ref=body.doc_ref,
            labels=body.labels,
            label_source=body.label_source,
            split=body.split,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await ex_store.save(example)
    version = await store.bump_labels_version(eval_set_id)
    saved = await ex_store.get_by_doc_key(eval_set_id, example.doc_key)
    return {"example": saved.model_dump(), "labels_version": version}


def _reject_unknown_fields(eval_set, labels: dict) -> None:
    """A label for a field the set does not declare is scored against nothing
    and silently ignored — which reads to the labeler as if their work was
    saved. Reject it instead."""
    declared = {s["name"] for s in eval_set.field_specs}
    unknown = sorted(set(labels) - declared)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={
                "unknown_fields": unknown,
                "declared_fields": sorted(declared),
                "hint": "labels must match the eval set's field_specs",
            },
        )


@router.get("/eval-sets/{eval_set_id}/examples", dependencies=[Depends(requires("eval:read"))])
async def list_examples(
    eval_set_id: str,
    split: str | None = None,
    limit: int = 100,
    offset: int = 0,
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
):
    if not await store.get(eval_set_id):
        raise HTTPException(status_code=404, detail="Eval set not found")
    rows = await ex_store.list_for_set(eval_set_id, split=split, limit=limit, offset=offset)
    return {
        "examples": [r.model_dump() for r in rows],
        "total": await ex_store.count_for_set(eval_set_id, split=split),
    }


@router.delete(
    "/eval-sets/{eval_set_id}/examples/{example_id}",
    status_code=204,
    dependencies=[Depends(requires("eval:write"))],
)
async def delete_example(
    eval_set_id: str,
    example_id: str,
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
):
    if not await ex_store.delete(example_id):
        raise HTTPException(status_code=404, detail="Example not found")
    await store.bump_labels_version(eval_set_id)
    return None


class ImportRequest(BaseModel):
    """CSV or JSONL keyed by `doc_key`.

    Importing by filename is deliberately *not* supported here: resolving a
    name to a content hash means reading the bytes, which this endpoint does
    not have. The UI resolves names against the source listing first and sends
    hashes, so a rename can never silently retarget a label.
    """

    format: str = "jsonl"
    content: str
    label_source: str = "imported"
    split: str = "train"


@router.post(
    "/eval-sets/{eval_set_id}/examples:import",
    dependencies=[Depends(requires("eval:write"))],
)
async def import_examples(
    eval_set_id: str,
    body: ImportRequest,
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
):
    eval_set = await store.get(eval_set_id)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")

    records = _parse_import(body)
    declared = {s["name"] for s in eval_set.field_specs}

    imported, errors = 0, []
    for i, rec in enumerate(records):
        doc_key = str(rec.pop("doc_key", "") or "").strip()
        split = str(rec.pop("split", body.split) or body.split)
        labels = {k: v for k, v in rec.items() if k in declared}
        try:
            await ex_store.save(EvalExampleBase(
                id="",
                eval_set_id=eval_set_id,
                doc_key=doc_key,
                labels=labels,
                label_source=body.label_source,
                split=split,
            ))
            imported += 1
        except ValueError as e:
            # One bad row must not discard the other 199. Report it and
            # continue — a partial import the caller can see beats an
            # all-or-nothing failure with no indication of which row broke.
            errors.append({"row": i, "error": str(e)})

    version = await store.bump_labels_version(eval_set_id) if imported else eval_set.labels_version
    return {"imported": imported, "errors": errors, "labels_version": version}


def _parse_import(body: ImportRequest) -> list[dict]:
    fmt = (body.format or "jsonl").lower()
    if fmt == "jsonl":
        out = []
        for line in body.content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=422, detail=f"invalid jsonl: {e}")
        return out
    if fmt == "csv":
        return list(csv.DictReader(io.StringIO(body.content)))
    raise HTTPException(status_code=422, detail=f"unsupported import format: {fmt!r}")


# ── consensus bootstrap ──────────────────────────────────────────────────


class BootstrapRequest(BaseModel):
    """Run several variants over the corpus and keep what they all agree on.

    `confirm` defaults False for the same reason `POST /sweep` does, but the
    stake is different and higher: a sweep spends money, while this writes
    *ground truth*. Every future comparison is measured against the corpus,
    so a mis-click here produces an eval set that looks populated and
    quietly encodes whatever the models happened to agree on.
    """

    variant_pipeline_ids: list[str] = Field(default_factory=list)
    limit: int = 500
    confirm: bool = False


def _structure_provider(pipeline) -> str | None:
    for step in getattr(pipeline, "steps", []) or []:
        if isinstance(step, dict) and step.get("op") == "structure":
            return step.get("provider")
    return None


@router.post(
    "/eval-sets/{eval_set_id}/bootstrap",
    dependencies=[Depends(requires("eval:write"))],
)
async def bootstrap_eval_set(
    eval_set_id: str,
    body: BootstrapRequest,
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
    s_store=Depends(get_source_store),
    c_store=Depends(get_connection_store),
    lt_store=Depends(get_lookup_table_store),
):
    eval_set = await store.get(eval_set_id)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")

    pipelines = []
    for pid in body.variant_pipeline_ids:
        p = await p_store.get(pid)
        if p is None:
            raise HTTPException(status_code=422, detail=f"variant pipeline not found: {pid}")
        pipelines.append(p)

    variant_rows, providers = {}, {}
    for p in pipelines:
        variant_rows[p.id] = await materialise_pipeline_rows(
            p, s_store, c_store, lt_store, limit=body.limit
        )
        providers[p.id] = _structure_provider(p)

    try:
        result = consensus(variant_rows, eval_set.to_field_specs(), providers=providers)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    written = 0
    if body.confirm:
        if not result["auto_accept"]:
            # 409 rather than a silent downgrade to review-only: the caller
            # asked to write, and pretending to comply while writing nothing
            # is worse than refusing.
            raise HTTPException(status_code=409, detail=result["warning"])
        for proposal in result["agreed"]:
            await ex_store.save(EvalExampleBase(
                id="",
                eval_set_id=eval_set_id,
                doc_key=proposal["doc_key"],
                labels=proposal["labels"],
                label_source=CONSENSUS_LABEL_SOURCE,
                split="train",
            ))
            written += 1

    version = (
        await store.bump_labels_version(eval_set_id) if written else eval_set.labels_version
    )
    return {**result, "written": written, "labels_version": version}


class ProposeRequest(BaseModel):
    """One model proposes labels for the whole corpus; a human confirms.

    The fastest cold start there is, and the one that most needs to stay
    visible: part of the corpus becomes this model's opinion, so scores
    computed against it are partly the model grading itself. Permanently
    tagged `judge` — the leaderboard's >50% warning depends on the tag
    surviving, and folding these into `human` would erase the only signal
    that the circularity exists.
    """

    pipeline_id: str
    limit: int = 500
    confirm: bool = False


@router.post(
    "/eval-sets/{eval_set_id}/propose",
    dependencies=[Depends(requires("eval:write"))],
)
async def propose_labels(
    eval_set_id: str,
    body: ProposeRequest,
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
    s_store=Depends(get_source_store),
    c_store=Depends(get_connection_store),
    lt_store=Depends(get_lookup_table_store),
):
    eval_set = await store.get(eval_set_id)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    pipeline = await p_store.get(body.pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=422, detail=f"pipeline not found: {body.pipeline_id}"
        )

    rows = await materialise_pipeline_rows(
        pipeline, s_store, c_store, lt_store, limit=body.limit
    )
    names = [s.name for s in eval_set.to_field_specs()]
    collapsed = collapse_rows_by_doc(rows, names)

    proposals = []
    for doc_key, values in sorted(collapsed.items()):
        labels = {k: v for k, v in values.items() if v is not None}
        # A document the judge abstained on carries no proposal. Writing an
        # all-null row would assert that the right answer is "nothing", and
        # every extractor that also abstains would score a hit on it.
        if labels:
            proposals.append({"doc_key": doc_key, "labels": labels})

    written = 0
    if body.confirm:
        for proposal in proposals:
            await ex_store.save(EvalExampleBase(
                id="",
                eval_set_id=eval_set_id,
                doc_key=proposal["doc_key"],
                labels=proposal["labels"],
                label_source="judge",
                split="train",
            ))
            written += 1

    version = (
        await store.bump_labels_version(eval_set_id) if written else eval_set.labels_version
    )
    return {
        "proposals": proposals,
        "written": written,
        "labels_version": version,
        "warning": (
            "These are model-proposed labels. Scores computed against them are "
            "partly this model grading itself — confirm them before trusting "
            "the leaderboard."
        ),
    }


# ── leaderboard ──────────────────────────────────────────────────────────


@router.get("/eval-sets/{eval_set_id}/leaderboard", dependencies=[Depends(requires("eval:read"))])
async def leaderboard(
    eval_set_id: str,
    limit: int = 50,
    store: EvalSetStore = Depends(get_eval_set_store),
    r_store: RunStore = Depends(get_run_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
):
    eval_set = await store.get(eval_set_id)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")

    runs = await r_store.list_for_eval_set(eval_set_id, limit=limit)
    entries = []
    for run in runs:
        scores = run.get("scores") or {}
        if not scores:
            continue
        stale = run.get("labels_version") != eval_set.labels_version
        entries.append({
            "run_id": run.get("id"),
            "pipeline_id": run.get("pipeline_id"),
            "status": run.get("status"),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "config_digest": run.get("config_digest"),
            "sweep_id": run.get("sweep_id"),
            "labels_version": run.get("labels_version"),
            # Scored against labels that have since changed: shown, but never
            # ranked. Silently comparing across a label edit is how an eval
            # system starts lying.
            "stale": stale,
            "macro_f1": scores.get("macro_f1"),
            "macro_f1_interval": scores.get("macro_f1_interval"),
            "n": scores.get("n"),
            "fields": scores.get("fields", []),
            "holdout": scores.get("holdout"),
            "regression": scores.get("regression"),
            # What this score cost and how fast it was. Reported beside the
            # score because "which config should I ship" is never answered
            # by accuracy alone — a point of F1 is rarely worth 10x the bill.
            "throughput": scores.get("throughput"),
        })

    ranked = _rank_with_ties([e for e in entries if not e["stale"]])
    label_sources = await ex_store.count_by_label_source(eval_set_id)
    return {
        "entries": entries,
        "ranking": ranked,
        "labels_version": eval_set.labels_version,
        "judge_labeled_warning": _judge_warning(label_sources),
    }


def _rank_with_ties(entries: list[dict]) -> list[dict]:
    """Rank by macro-F1, but award the same rank to any entry whose confidence
    interval overlaps the leader's.

    A leaderboard that declares 94.1% the winner over 91.7% on n=8 is
    rendering noise as a decision, and it is worse than no leaderboard because
    people act on it. Overlapping intervals are reported as tied.
    """
    scored = [e for e in entries if e.get("macro_f1") is not None]
    scored.sort(key=lambda e: e["macro_f1"], reverse=True)

    out: list[dict] = []
    rank = 0
    prev: dict | None = None
    for entry in scored:
        interval = tuple(entry.get("macro_f1_interval") or (0.0, 1.0))
        if prev is None:
            rank = 1
        else:
            prev_interval = tuple(prev.get("macro_f1_interval") or (0.0, 1.0))
            if not intervals_overlap(interval, prev_interval):
                rank += 1
            # else: overlapping — same rank as the entry above.
        row = dict(entry)
        row["rank"] = rank
        row["tied_with_leader"] = rank == 1 and len(out) > 0
        out.append(row)
        prev = entry
    return out


@router.get(
    "/eval-sets/{eval_set_id}/fields/{field}/failures",
    dependencies=[Depends(requires("eval:read"))],
)
async def field_failures(
    eval_set_id: str,
    field: str,
    run_id: str | None = Query(default=None),
    store: EvalSetStore = Depends(get_eval_set_store),
    r_store: RunStore = Depends(get_run_store),
):
    """Every document where `field` did not match, for one run.

    Defaults to the most recent scored run so the drill-down works straight
    off the leaderboard without the caller tracking run ids.
    """
    if not await store.get(eval_set_id):
        raise HTTPException(status_code=404, detail="Eval set not found")

    runs = await r_store.list_for_eval_set(eval_set_id, limit=50)
    run = None
    if run_id:
        run = next((r for r in runs if r.get("id") == run_id), None)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found for this eval set")
    else:
        run = next((r for r in runs if (r.get("scores") or {}).get("failures") is not None), None)
    if run is None:
        raise HTTPException(status_code=404, detail="No scored run for this eval set")

    failures = (run.get("scores") or {}).get("failures") or []
    return {
        "run_id": run.get("id"),
        "field": field,
        "failures": [f for f in failures if f.get("field") == field],
    }


# ── sweeps ───────────────────────────────────────────────────────────────


class SweepRequest(BaseModel):
    """A config matrix to expand into one run per cell.

    `confirm` defaults to False: the first call is always an estimate.
    """

    pipeline_id: str
    matrix: dict[str, list] = Field(default_factory=dict)
    confirm: bool = False


@router.post("/eval-sets/{eval_set_id}/sweep", dependencies=[Depends(requires("eval:write"))])
async def launch_sweep(
    eval_set_id: str,
    body: SweepRequest,
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
    re_store=Depends(get_run_event_store),
    s_store=Depends(get_source_store),
    d_store=Depends(get_destination_store),
    c_store=Depends(get_connection_store),
    lt_store=Depends(get_lookup_table_store),
):
    eval_set = await store.get(eval_set_id)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    pipeline = await p_store.get(body.pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if getattr(pipeline, "pipeline_type", "transform") != "eval":
        raise HTTPException(
            status_code=422,
            detail="sweeps run eval pipelines; this pipeline is not one",
        )
    # Checked before the estimate, not at confirm: refusing later would let
    # someone build a matrix, read a cost, and decide to spend — only to be
    # told the corpus never matched. Every cell would have scored zero.
    await validate_eval_corpus_match(pipeline, eval_set_id, store)

    cells = _expand_matrix(body.matrix)
    max_cells = get_settings().eval_max_sweep_cells
    if len(cells) > max_cells:
        raise HTTPException(
            status_code=422,
            detail=(
                f"sweep expands to {len(cells)} cells, above the cap of {max_cells}. "
                "Narrow the matrix or raise DTE_EVAL_MAX_SWEEP_CELLS."
            ),
        )

    # Every cell must be applicable *before* a price is quoted. Validating
    # only on the way to enqueueing lets someone read a clean estimate for a
    # matrix that cannot run, then discover the typo at the moment they
    # commit to spending — the same trap the corpus-match check sits above
    # the estimate to avoid. `apply_cell` is pure, so this costs nothing.
    for cell in cells:
        try:
            apply_cell(pipeline, cell)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    documents = await ex_store.count_for_set(eval_set_id)
    per_doc, basis = await _cost_per_document(r_store, eval_set_id)
    estimate = {
        "cells": len(cells),
        "documents": documents,
        # Worst case: nothing cached. The extract cache means a re-run of a
        # cell costs nothing, so this is a ceiling, not a forecast.
        "uncached_calls": len(cells) * documents,
        "est_cost_usd": None if per_doc is None else per_doc * len(cells) * documents,
        "cost_basis": basis,
        "matrix": cells,
    }

    if not body.confirm:
        # Cancelling enqueues nothing — that is the entire point of the
        # two-step flow, and it is asserted in the scenario suite.
        estimate["enqueued"] = False
        return estimate

    sweep_id = str(_uuid.uuid4())
    runs = []
    for cell in cells:
        # Each cell becomes a real pipeline. The leaderboard groups by
        # config_digest, and a digest only exists for a pipeline that was
        # actually run — a sweep that reported cells without creating them
        # would leave an empty leaderboard that reads as "every config
        # failed" rather than "nothing ran".
        try:
            variant = apply_cell(pipeline, cell)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        vid = variant_id(pipeline, cell)
        variant.id = vid
        variant.name = await _unique_variant_name(
            p_store, variant_name(pipeline, cell), vid
        )
        await p_store.save(variant)
        run_id = await start_eval_run(
            vid, eval_set_id=eval_set_id, sweep_id=sweep_id,
            p_store=p_store, r_store=r_store, re_store=re_store,
            s_store=s_store, d_store=d_store, c_store=c_store,
            lt_store=lt_store, es_store=store, ee_store=ex_store,
        )
        runs.append({"cell": cell, "pipeline_id": vid, "run_id": run_id})

    estimate["enqueued"] = True
    estimate["sweep_id"] = sweep_id
    estimate["runs"] = runs
    return estimate


@router.get("/sweeps/{sweep_id}/comparison", dependencies=[Depends(requires("eval:read"))])
async def sweep_comparison(
    sweep_id: str,
    limit: int = Query(200, ge=1, le=1000),
    store: EvalSetStore = Depends(get_eval_set_store),
    ex_store: EvalExampleStore = Depends(get_eval_example_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
    s_store=Depends(get_source_store),
    c_store=Depends(get_connection_store),
    lt_store=Depends(get_lookup_table_store),
):
    """Side-by-side outputs for one sweep, with or without labels.

    This is the surface plan 053 exists to add. The leaderboard needs
    ground truth before it will show anything, which is why the harness sat
    empty — so this endpoint answers the parts of the question that need no
    labels at all: where the configs disagree, what each cost, how slow
    each was, how often each abstained. Scores appear alongside once labels
    exist; their absence is the normal case, not an error.

    Rows are re-materialised rather than read back from the run, because an
    eval run writes no output. That is affordable precisely because plan
    050 caches extraction by document content and structure by text hash:
    re-reading a finished cell parses no PDF and calls no model, so opening
    this page costs nothing beyond a compile.
    """
    runs = await r_store.list_for_sweep(sweep_id, limit=limit)
    if not runs:
        raise HTTPException(status_code=404, detail=f"No runs found for sweep '{sweep_id}'")

    eval_set_id = next((r.get("eval_set_id") for r in runs if r.get("eval_set_id")), None)
    eval_set = await store.get(eval_set_id) if eval_set_id else None
    if eval_set is None:
        raise HTTPException(
            status_code=422,
            detail=f"sweep '{sweep_id}' is not bound to an eval set, so there is nothing to compare against",
        )
    specs = eval_set.to_field_specs()

    cells = []
    for run in runs:
        pipeline = await p_store.get(run["pipeline_id"])
        rows: list[dict] = []
        if pipeline is not None and run.get("status") == "completed":
            try:
                rows = await materialise_pipeline_rows(
                    pipeline, s_store, c_store, lt_store, limit=limit
                )
            except Exception as exc:  # pragma: no cover - surfaced, not raised
                # One cell failing to re-materialise must not blank the whole
                # comparison — the other columns are still the answer the user
                # came for. The cell reports why instead.
                run = {**run, "status": "unavailable", "error": str(exc)}
        cells.append({
            "cell_id": run["pipeline_id"],
            "pipeline_id": run["pipeline_id"],
            "run_id": run["id"],
            "status": run.get("status"),
            "error": run.get("error"),
            "cell": _cell_from_pipeline(pipeline),
            "rows": rows,
            "scores": run.get("scores") or {},
            "throughput": (run.get("scores") or {}).get("throughput") or {},
        })

    examples = await ex_store.list_for_set(eval_set.id, limit=10_000)
    labelled = {e.doc_key for e in examples}

    out = build_comparison(cells, specs, labelled_doc_keys=labelled)
    out["sweep_id"] = sweep_id
    out["eval_set_id"] = eval_set.id
    out["labels_version"] = eval_set.labels_version
    # Carried so the grid can show which cells are still running without a
    # second request; a sweep is polled while it fills in.
    out["pending"] = sum(
        1 for r in runs if r.get("status") in ("pending", "running")
    )
    return out


def _cell_from_pipeline(pipeline) -> dict:
    """The config that names a column, read back off the variant pipeline.

    The sweep's `cell` dict is not persisted anywhere — only the variant it
    produced is. Reconstructing the interesting keys from the structure step
    keeps the column headers honest even for a sweep launched months ago.
    """
    if pipeline is None:
        return {}
    for step in getattr(pipeline, "steps", None) or []:
        if isinstance(step, dict) and step.get("op") == "structure":
            out = {"provider": step.get("provider")}
            model = (step.get("params") or {}).get("model")
            if model:
                out["model"] = model
            instructions = (step.get("model") or {}).get("instructions")
            if instructions:
                out["instructions"] = instructions
            return out
    return {}


class PromoteRequest(BaseModel):
    """Turn the winning eval config into a shippable transform pipeline."""

    pipeline_id: str
    new_pipeline_id: str
    name: str
    output_id: str


@router.post(
    "/eval-sets/{eval_set_id}/promote",
    status_code=201,
    dependencies=[Depends(requires("eval:write"))],
)
async def promote_pipeline(
    eval_set_id: str,
    body: PromoteRequest,
    store: EvalSetStore = Depends(get_eval_set_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
):
    """Copy a scored config into a transform pipeline that writes somewhere.

    This closes the loop the whole harness exists for. Without it, the
    answer to "which config should I ship" is a number someone re-types
    into the builder by hand — which is exactly where the config that was
    measured and the config that ships start to diverge.

    The steps are copied verbatim for that reason: the promoted pipeline
    must hash to the same `config_digest` that earned the score, or the
    score is about something else.
    """
    if not await store.get(eval_set_id):
        raise HTTPException(status_code=404, detail="Eval set not found")
    source = await p_store.get(body.pipeline_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if getattr(source, "pipeline_type", "transform") != "eval":
        raise HTTPException(
            status_code=422,
            detail="only an eval pipeline can be promoted; this one is not",
        )
    if not body.output_id:
        raise HTTPException(
            status_code=422,
            detail="a promoted pipeline writes real output, so it needs a destination",
        )
    if await p_store.get(body.new_pipeline_id):
        raise HTTPException(
            status_code=409,
            detail=f"pipeline '{body.new_pipeline_id}' already exists",
        )

    promoted = detached_copy(source)
    promoted.id = body.new_pipeline_id
    promoted.name = body.name
    promoted.pipeline_type = "transform"
    promoted.output_id = body.output_id
    await p_store.save(promoted)
    return {
        "pipeline_id": body.new_pipeline_id,
        "config_digest": config_digest(promoted),
    }


async def _cost_per_document(r_store, eval_set_id: str):
    """Dollars per document, measured from this set's most recent priced run.

    Nothing can know the token count of a call that has not happened, so the
    only honest estimate extrapolates from what a comparable run actually
    spent. Returns `(None, reason)` whenever that basis is missing — a
    launcher that quotes a confident price it invented is worse than one
    that admits it does not know yet, because the invented figure is what
    gets budgeted against.
    """
    runs = await r_store.list_for_eval_set(eval_set_id, limit=50)
    for run in runs:
        tp = ((run.get("scores") or {}).get("throughput")) or {}
        cost = tp.get("cost_usd")
        calls = tp.get("n_calls") or 0
        if cost is None:
            continue
        if not calls:
            # A fully-cached run cost nothing because the work was already
            # paid for. Using $0 as the rate would quote a free sweep that
            # then bills for every config that has never run.
            continue
        return cost / calls, f"measured from run {run['id'][:8]} (${cost:.4f} over {calls} calls)"
    return None, "no priced run yet — launch once to measure the per-document cost"


async def _unique_variant_name(p_store, name: str, variant_id_: str) -> str:
    """A display name for one cell that will not violate UNIQUE(tenant, name).

    Cell names are derived from the root config plus this cell's overrides,
    which is what stops them accumulating into "demo · instructions=v3 ·
    provider=regex · provider=claude". The cost is that two different
    configs can want the same name — the root swept one way, and a variant
    of it swept the same way — and rows left behind by the nesting bug make
    that likely on existing installs.

    Identity is the id, so the name is free to be disambiguated. The short
    digest is already in the id, so borrowing it keeps the two consistent
    and the result deterministic: re-running the sweep produces the same
    name rather than climbing a counter.
    """
    # A scan, because there is no lookup-by-name on the store. Acceptable
    # here: it runs once per cell of a sweep that is capped at 50.
    for existing in await p_store.list(limit=1000):
        if existing.name == name and existing.id != variant_id_:
            return f"{name} ({variant_id_.rsplit('__', 1)[-1][:7]})"
    return name


def _expand_matrix(matrix: dict[str, list]) -> list[dict]:
    """Cartesian product of the matrix axes, in declaration order."""
    if not matrix:
        return []
    keys = list(matrix)
    values = [matrix[k] or [] for k in keys]
    if any(not v for v in values):
        raise HTTPException(
            status_code=422, detail="every matrix axis needs at least one value"
        )
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]
