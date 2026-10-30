"""Join extraction output to labels and score it (plan 051 task 7).

`_run_body` materialises the compiled table and hands the rows here. This
module owns the two decisions that determine *what* gets compared; the
arithmetic afterwards belongs to `dte.evals.scoring`.

**Rows are collapsed back to documents.** `extract` at page granularity fans
one document out to one row per page, but a label is per document. The invoice
total appears on one page and the vendor on another, so the first non-null
value of each field across a document's rows reassembles the document the
human actually labeled.

**Both directions of the join are failures, and neither is silent.** A
document the run produced but nobody labeled is *not* a miss — there is
nothing to compare it to, and counting it would punish an extractor for the
labeler's backlog. A document that *was* labeled but which the run never
produced is a silent miss on every field: without that, an extractor that
crashes on half the corpus scores perfectly on the half it managed.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from dte.evals.scoring import FieldSpec, score_corpus, wilson_interval

# The column carrying the document reference. Its value is the artifact
# store's key, the same value `eval_examples.doc_key` holds — which is what
# makes the join a lookup rather than a path-matching heuristic.
DOC_REF_COLUMN = "artifact_ref"

# The compiler writes the reference as a URI (`artifact://<sha256>`), while
# `eval_examples.doc_key` stores the bare digest. Normalising here rather than
# widening the model's validator keeps the stored key canonical: one form on
# disk, one place that knows about the scheme.
_ARTIFACT_SCHEME = "artifact://"


def _doc_key_from_ref(ref: Any) -> str | None:
    if not isinstance(ref, str) or not ref.strip():
        return None
    key = ref.strip()
    if key.startswith(_ARTIFACT_SCHEME):
        key = key[len(_ARTIFACT_SCHEME):]
    return key.lower() or None


def _is_null(value: Any) -> bool:
    """A model that answers `""` has abstained. Treating it as an answer turns
    a correct abstention into a wrong one, which is the exact distinction the
    whole scoring module exists to preserve."""
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def collapse_rows_by_doc(
    rows: Iterable[dict],
    field_names: Sequence[str],
) -> dict[str, dict]:
    """Reduce many rows per document to one predicted value per field.

    Rows with no `artifact_ref` are dropped: they cannot be attributed to a
    label, and scoring them against nothing would count as a miss for whichever
    document happened to sort next to them.
    """
    collapsed: dict[str, dict] = {}
    for row in rows:
        doc_key = _doc_key_from_ref(row.get(DOC_REF_COLUMN))
        if doc_key is None:
            continue
        target = collapsed.setdefault(doc_key, {})
        for name in field_names:
            if target.get(name) is None and not _is_null(row.get(name)):
                target[name] = row.get(name)
    # Normalise: every scored field present, absent ones explicitly None so
    # `score_corpus` reads them as a miss rather than a KeyError.
    for values in collapsed.values():
        for name in field_names:
            values.setdefault(name, None)
    return collapsed


def _normalise_labels(labels: Any, field_names: Sequence[str]) -> dict:
    labels = labels if isinstance(labels, dict) else {}
    return {
        name: (None if _is_null(labels.get(name)) else labels.get(name))
        for name in field_names
    }


def _score_split(
    predicted: dict[str, dict],
    examples: Sequence[Any],
    specs: Sequence[FieldSpec],
    field_names: Sequence[str],
    collect_failures: bool,
) -> tuple[dict, list[dict]]:
    pairs: list[tuple[dict, dict]] = []
    failures: list[dict] = []

    for example in examples:
        expected = _normalise_labels(getattr(example, "labels", None), field_names)
        # A labeled document the run never produced: every field is a miss.
        actual = predicted.get(example.doc_key, {name: None for name in field_names})
        pairs.append((expected, actual))

    corpus = score_corpus(pairs, specs)
    result = corpus.as_dict()
    result["fields"] = [m.as_dict() for m in corpus.fields.values()]

    # Wilson over "documents whose every field matched" — the interval is
    # about how much of the score is sampling noise, so it must be computed on
    # documents, the unit that was actually sampled.
    exact = 0
    for expected, actual in pairs:
        single = score_corpus([(expected, actual)], specs)
        if single.macro_f1 == 1.0:
            exact += 1
    result["macro_f1_interval"] = list(wilson_interval(exact, len(pairs)))

    if collect_failures:
        from dte.evals.comparators import compare

        for example, (expected, actual) in zip(examples, pairs, strict=True):
            for spec in specs:
                exp, act = expected.get(spec.name), actual.get(spec.name)
                if exp is None and act is None:
                    continue
                matched = (
                    exp is not None
                    and act is not None
                    and compare(exp, act, spec.type, spec.comparator).matched
                )
                if not matched:
                    failures.append({
                        "doc_key": example.doc_key,
                        "doc_ref": getattr(example, "doc_ref", None),
                        "field": spec.name,
                        "expected": exp,
                        "actual": act,
                        "split": getattr(example, "split", "train"),
                    })

    return result, failures


def join_and_score(
    rows: Iterable[dict],
    examples: Sequence[Any],
    specs: Sequence[FieldSpec],
    collect_failures: bool = False,
) -> dict:
    """Score one eval run. Returns the payload written to `runs.scores`.

    `train` examples produce the headline score; `holdout` is scored
    separately and reported alongside. A large gap between them means the
    prompt was tuned to the eval set — visible rather than inferred.
    """
    field_names = [s.name for s in specs]
    rows = list(rows)
    predicted = collapse_rows_by_doc(rows, field_names)

    train = [e for e in examples if getattr(e, "split", "train") != "holdout"]
    holdout = [e for e in examples if getattr(e, "split", "train") == "holdout"]

    result, failures = _score_split(
        predicted, train, specs, field_names, collect_failures
    )

    if holdout:
        holdout_result, holdout_failures = _score_split(
            predicted, holdout, specs, field_names, collect_failures
        )
        result["holdout"] = holdout_result
        failures.extend(holdout_failures)
    else:
        # None, never 0.0 — an unmeasured holdout must not render as a score.
        result["holdout"] = None

    label_sources: dict[str, int] = {}
    for e in examples:
        src = getattr(e, "label_source", "human")
        label_sources[src] = label_sources.get(src, 0) + 1
    result["label_sources"] = label_sources
    result["documents_produced"] = len(predicted)

    if collect_failures:
        result["failures"] = failures

    return result
