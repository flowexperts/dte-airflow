"""Consensus bootstrap — turning several cheap variants into ground truth.

The failure this module exists to prevent is not a wrong score. It is an
eval set with nothing in it. Hand-labeling a few hundred documents is
nobody's Tuesday, so the harness that demands it first sits empty forever.
Running N variants over the corpus and keeping only what they unanimously
agree on typically settles the large, boring majority and leaves a few
dozen genuinely hard documents for a human — a labeled set in an afternoon
instead of a fortnight.

That makes the definition of "agree" the whole feature, and three choices
carry it:

**Agreement is decided by the eval set's own comparators**, not string
equality. `$1,240.50` and `1240.50` are the same answer. Comparing them
literally would route most of a currency corpus into the review queue and
delete the time saving this is here to produce — while looking like the
models disagreed far more than they did.

**Null is not a vote.** Variants that all abstain have agreed on nothing.
Writing that as ground truth would teach the corpus that the correct answer
is "no answer", and every extractor that abstains would then score well —
the precise failure `scoring.py` splits `tn` from `fn` to avoid.

**Unanimity, not majority.** A majority vote among variants that share a
base model is that model's opinion counted twice. Two-of-three is exactly
the kind of "mostly right" label that makes a corpus quietly wrong, and a
quietly wrong corpus is worse than no corpus: every future comparison
inherits the error and reports it with confidence.

Related: `providers` gates *auto-accept*, not the computation. Three
prompts against one model agreeing measures the prompt, not the truth, so
the caller is told to review rather than accept — but the proposals are
still produced, since a human confirming them is a perfectly good use of
the same work.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from dte.evals.comparators import compare
from dte.evals.runner import collapse_rows_by_doc
from dte.evals.scoring import FieldSpec

# `label_source` written for anything this module proposes and the caller
# accepts. Never collapsed into "human": knowing a label came from models
# agreeing with each other is essential context when the scores look good.
CONSENSUS_LABEL_SOURCE = "consensus"


def _values_agree(values: Sequence[Any], spec: FieldSpec) -> bool:
    """All non-null and mutually equivalent under the field's comparator.

    Compared pairwise against the first value rather than transitively: the
    comparators are tolerance-based, so equivalence is not guaranteed to be
    transitive (a≈b and b≈c does not give a≈c at the edge of a tolerance).
    Anchoring on one value keeps the relation well-defined.
    """
    if any(v is None for v in values):
        return False
    head, *rest = values
    for other in rest:
        try:
            if not compare(head, other, spec.type, spec.comparator).matched:
                return False
        except ValueError:
            # Comparators raise on a null side; already excluded above, so
            # this is an unparseable value — treat as disagreement and let
            # a human look at it rather than guessing.
            return False
    return True


def consensus(
    variant_rows: Mapping[str, list[dict]],
    specs: Sequence[FieldSpec],
    providers: Mapping[str, str] | None = None,
) -> dict:
    """Propose labels from agreement across variants.

    `variant_rows` maps a variant label to that variant's output rows.
    Returns `{agreed, disagreed, auto_accept, warning, n_documents}` —
    proposals only. Writing them is the caller's decision, so a bootstrap
    can be inspected before it becomes ground truth.
    """
    if len(variant_rows) < 2:
        raise ValueError(
            "consensus needs at least two variants — one variant agreeing "
            "with itself is not evidence, it is that model's opinion"
        )

    names = [s.name for s in specs]
    by_spec = {s.name: s for s in specs}
    collapsed = {
        label: collapse_rows_by_doc(rows, names)
        for label, rows in variant_rows.items()
    }

    # Union, not intersection: a document one variant never produced is a
    # disagreement worth surfacing, not a row to silently drop.
    doc_keys = sorted({key for c in collapsed.values() for key in c})

    agreed: list[dict] = []
    disagreed: list[dict] = []
    for doc_key in doc_keys:
        per_field = {
            name: {
                label: c.get(doc_key, {}).get(name)
                for label, c in collapsed.items()
            }
            for name in names
        }
        settled: dict[str, Any] = {}
        contested: dict[str, dict[str, Any]] = {}
        for name in names:
            votes = per_field[name]
            if _values_agree(list(votes.values()), by_spec[name]):
                settled[name] = next(iter(votes.values()))
            else:
                contested[name] = votes

        if contested:
            disagreed.append({
                "doc_key": doc_key,
                "agreed_fields": settled,
                "candidates": contested,
            })
        else:
            agreed.append({"doc_key": doc_key, "labels": settled})

    warning = None
    auto_accept = True
    distinct = {(providers or {}).get(label) for label in variant_rows}
    distinct.discard(None)
    if providers and len(distinct) < 2:
        auto_accept = False
        warning = (
            "All variants share a provider. Agreement between prompts against "
            "the same model reflects that model's blind spots, not ground "
            "truth — review these before accepting."
        )

    return {
        "agreed": agreed,
        "disagreed": disagreed,
        "auto_accept": auto_accept,
        "warning": warning,
        "n_documents": len(doc_keys),
    }
