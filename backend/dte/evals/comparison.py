"""What a sweep tells you before anyone has labelled anything.

Plan 051's leaderboard opens on "No comparable runs yet." That default is
why the harness sat empty: it demands ground truth before it will show you
anything at all, and hand-labelling a corpus is nobody's Tuesday. Every
comparable product — Braintrust, LangSmith, Phoenix — opens the other way
round: run N configs, look at the outputs side by side, and curate labels
out of what you were already reviewing.

A sweep with no labels answers most of the question on its own:

- **Where do the configs disagree?** Decided by the eval set's own
  comparators, so `$1,240.50` and `1240.5` count as agreement. Comparing
  literally would route most of a currency corpus into the disagreement
  list and destroy the signal.
- **What did each cost, and how slow was it?** Already measured per run.
- **How often did each abstain?** Abstention is not the same as being
  wrong, and a config that answers nothing must not read as clean.

And the disagreements are simultaneously the review queue — so the
label-free view is also the shortest path *to* labels. Scores are an
addition to this payload when labels exist, never a precondition for it.

Three rules inherited deliberately from `bootstrap.py`, because a
comparison that measured agreement differently from the thing that writes
labels would offer you an "accept 41 agreed" button for a number the
accept step then disagrees with:

**Null is not agreement.** Configs that all abstained agreed on nothing.
**Union, not intersection.** A document one config never produced is a
disagreement worth seeing, not a row to quietly drop.
**Comparators, not equality.** Formatting-forgiving, semantically strict.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from dte.evals.bootstrap import _values_agree
from dte.evals.runner import collapse_rows_by_doc
from dte.evals.scoring import FieldSpec, intervals_overlap

# The column the compiler writes the document reference into, and the
# human-readable path beside it. Both are already on every extracted row.
_DOC_REF_CANDIDATES = ("path", "file_path", "source_path")


def _doc_ref_index(cells: Sequence[Mapping[str, Any]]) -> dict[str, str | None]:
    """A displayable path per document, for the inspector link.

    Taken from whichever cell produced one. The path is a property of the
    document, not of the config that read it, so the first non-null wins.
    """
    from dte.evals.runner import _doc_key_from_ref

    refs: dict[str, str | None] = {}
    for cell in cells:
        for row in cell.get("rows") or []:
            key = _doc_key_from_ref(row.get("artifact_ref"))
            if key is None or refs.get(key):
                continue
            for candidate in _DOC_REF_CANDIDATES:
                value = row.get(candidate)
                if isinstance(value, str) and value.strip():
                    refs[key] = value
                    break
            refs.setdefault(key, None)
    return refs


def _structure_errors(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every `structure_meta.error` on a cell's rows.

    The column arrives as a JSON string from DuckDB and as a dict from the
    preview path. Accepting only one would make failures invisible on
    exactly one of them — the worse half of a silent failure.
    """
    out: list[str] = []
    for row in rows:
        meta = row.get("structure_meta")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                continue
        if isinstance(meta, Mapping) and meta.get("error"):
            out.append(str(meta["error"]))
    return out


def _rank_cells(cells: list[dict]) -> None:
    """Rank scored cells in place, rendering statistical ties as ties.

    Mirrors the leaderboard's `_rank_with_ties`. A config 2pp ahead on n=8
    has not won anything, and awarding it a rank-1 badge sends someone off
    to ship a config that is not actually better — the most expensive thing
    a comparison surface can get wrong.
    """
    scored = [c for c in cells if c.get("macro_f1") is not None]
    if not scored:
        return
    scored.sort(key=lambda c: c["macro_f1"], reverse=True)
    leader = scored[0]
    leader_interval = leader.get("macro_f1_interval")

    def _ties_leader(cell: dict) -> bool:
        interval = cell.get("macro_f1_interval")
        return bool(
            leader_interval
            and interval
            and intervals_overlap(tuple(interval), tuple(leader_interval))
        )

    for cell in scored[1:]:
        cell["tied_with_leader"] = _ties_leader(cell)
    # The leader trivially overlaps itself, so asking the same question of it
    # would always answer yes. What the flag has to mean for the leader is
    # "someone else is level with me" — that is what decides whether the UI
    # awards a winner badge at all.
    leader["tied_with_leader"] = any(_ties_leader(c) for c in scored[1:])

    rank = 0
    previous: dict | None = None
    for index, cell in enumerate(scored, start=1):
        same_as_previous = (
            previous is not None
            and previous.get("macro_f1_interval")
            and cell.get("macro_f1_interval")
            and intervals_overlap(
                tuple(cell["macro_f1_interval"]), tuple(previous["macro_f1_interval"])
            )
        )
        if not same_as_previous:
            rank = index
        cell["rank"] = rank
        previous = cell


def build_comparison(
    cells: Sequence[Mapping[str, Any]],
    specs: Sequence[FieldSpec],
    labelled_doc_keys: Iterable[str] | None = None,
) -> dict:
    """Assemble the side-by-side view of one sweep.

    `cells` is one entry per config: `cell_id`, `pipeline_id`, `run_id`,
    `status`, the `cell` overrides that define it, its output `rows`, and
    optionally its `scores` and `throughput`.

    Returns cells (metrics, plus scores and rank where labels exist), field
    agreement rates, per-document values, and a label summary.
    """
    if not cells:
        raise ValueError("a comparison needs at least one cell — this sweep has no cells")
    if not specs:
        raise ValueError("a comparison needs at least one field to compare")

    names = [s.name for s in specs]
    by_name = {s.name: s for s in specs}
    labelled = set(labelled_doc_keys or ())

    collapsed = {
        cell["cell_id"]: collapse_rows_by_doc(cell.get("rows") or [], names)
        for cell in cells
    }
    refs = _doc_ref_index(cells)

    # Union: a document only one config produced belongs in the list, and it
    # belongs there as a disagreement.
    doc_keys = sorted({key for c in collapsed.values() for key in c})

    # Agreement is undefined with a single config — None, not 1.0. Rendering
    # "100% agreement" for one config would read as a strong result when
    # nothing was compared.
    comparable = len(cells) > 1

    documents: list[dict] = []
    disagreements = {name: 0 for name in names}

    for doc_key in doc_keys:
        values = {
            cell_id: {
                name: collapsed[cell_id].get(doc_key, {}).get(name) for name in names
            }
            for cell_id in collapsed
        }
        agrees = True
        # Per field, not just rolled up: the table marks the cell that
        # disagrees, and it must mark it from *this* — the comparators —
        # rather than recomputing with string equality on the client, where
        # `1240.50` and `1240.5` would render as a disagreement directly
        # under a field panel calling them agreement.
        field_agrees: dict[str, bool | None] = dict.fromkeys(names, None)
        if comparable:
            for name in names:
                votes = [values[cell_id][name] for cell_id in values]
                ok = _values_agree(votes, by_name[name])
                field_agrees[name] = ok
                if not ok:
                    disagreements[name] += 1
                    agrees = False
        documents.append({
            "doc_key": doc_key,
            "doc_ref": refs.get(doc_key),
            "values": values,
            "agrees": agrees if comparable else None,
            "field_agrees": field_agrees,
        })

    # Disagreements first — they are the reason to open this page, and at a
    # real corpus size burying them under agreeing rows makes it useless.
    documents.sort(key=lambda d: (d["agrees"] is not False, d["doc_key"]))

    total_docs = len(doc_keys)
    fields = [
        {
            "name": name,
            "agreement_rate": (
                None if not comparable or not total_docs
                else round((total_docs - disagreements[name]) / total_docs, 4)
            ),
            "disagreement_count": disagreements[name] if comparable else None,
        }
        for name in names
    ]

    out_cells: list[dict] = []
    for cell in cells:
        predicted = collapsed[cell["cell_id"]]
        errors = _structure_errors(cell.get("rows") or [])
        answered = sum(
            1 for values in predicted.values() for name in names
            if values.get(name) is not None
        )
        slots = len(predicted) * len(names)
        throughput = cell.get("throughput") or {}
        scores = cell.get("scores") or {}
        out_cells.append({
            "cell_id": cell["cell_id"],
            "pipeline_id": cell.get("pipeline_id"),
            "run_id": cell.get("run_id"),
            "status": cell.get("status"),
            "cell": cell.get("cell") or {},
            "documents": len(predicted),
            # None when the cell produced nothing — a rate over zero slots
            # is not 0.0, it is unmeasured.
            "null_rate": None if not slots else round((slots - answered) / slots, 4),
            # A null is a finding — the model looked and declined. An error
            # is the absence of one. Folding them together renders a column
            # that failed on every row identically to an honest abstainer,
            # which is how a missing API key reads as "claude is bad at this".
            "error_count": len(errors),
            "error_sample": errors[0] if errors else None,
            "cost_usd": throughput.get("cost_usd"),
            "latency_p95_ms": throughput.get("latency_p95_ms"),
            "cache_hit_rate": throughput.get("cache_hit_rate"),
            # Absent, not zero, when unlabelled.
            "macro_f1": scores.get("macro_f1"),
            "macro_f1_interval": scores.get("macro_f1_interval"),
            "n": scores.get("n"),
        })

    _rank_cells(out_cells)

    agreed_unlabeled = sum(
        1 for d in documents if d["agrees"] is True and d["doc_key"] not in labelled
    )

    # Whether accepting the agreement is a defensible label write, decided
    # by the same rule `bootstrap` enforces. Reproduced rather than inferred
    # later because the UI has to know *before* it offers the button: a
    # button that promises acceptance and then 409s is worse than one that
    # says "review these" up front — and configs sharing a provider is the
    # common case, since sweeping models or prompts holds the provider fixed.
    providers = {
        c["cell"].get("provider") for c in out_cells if (c.get("cell") or {}).get("provider")
    }
    auto_accept = len(providers) >= 2
    warning = None if auto_accept else (
        "These configs share a provider. Agreement between prompts against "
        "the same model reflects that model's blind spots, not ground truth "
        "— review before accepting."
    )

    return {
        "cells": out_cells,
        "fields": fields,
        "documents": documents,
        "labels": {
            "total": len(labelled & set(doc_keys)),
            "agreed_unlabeled": agreed_unlabeled,
            "auto_accept": auto_accept,
            "warning": warning,
        },
    }
