"""The join-and-score step of an eval run (plan 051 task 7).

`_run_body` materialises the compiled table, then hands rows here. These are
the parts that decide *what* gets compared; the arithmetic afterwards is
`dte.evals.scoring`, tested separately.
"""
from __future__ import annotations

import pytest

from dte.evals.runner import collapse_rows_by_doc, join_and_score
from dte.evals.scoring import FieldSpec
from dte.models.eval import EvalExampleBase

KEY_A = "a" * 64
KEY_B = "b" * 64
KEY_C = "c" * 64

SPECS = [FieldSpec(name="total", type="numeric"), FieldSpec(name="vendor", type="string")]


def _example(doc_key: str, labels: dict, **kw) -> EvalExampleBase:
    return EvalExampleBase(
        id=kw.pop("id", ""),
        eval_set_id=kw.pop("eval_set_id", "es1"),
        doc_key=doc_key,
        labels=labels,
        label_source=kw.pop("label_source", "human"),
        **kw,
    )


# ── collapsing pages back to documents ───────────────────────────────────


def test_one_row_per_document_passes_through():
    rows = [{"artifact_ref": KEY_A, "total": "1240.50", "vendor": "Acme"}]
    assert collapse_rows_by_doc(rows, ["total", "vendor"]) == {
        KEY_A: {"total": "1240.50", "vendor": "Acme"}
    }


def test_pages_collapse_to_first_non_null_per_field():
    """`extract` at page granularity fans one document out to one row per
    page, but a label is per document. The invoice total appears on one page
    and the vendor on another; taking the first non-null of each reassembles
    the document the human actually labeled."""
    rows = [
        {"artifact_ref": KEY_A, "total": None, "vendor": "Acme"},
        {"artifact_ref": KEY_A, "total": "1240.50", "vendor": None},
        {"artifact_ref": KEY_A, "total": "9999.00", "vendor": "Ignored"},
    ]
    assert collapse_rows_by_doc(rows, ["total", "vendor"]) == {
        KEY_A: {"total": "1240.50", "vendor": "Acme"}
    }


def test_artifact_uri_scheme_is_stripped():
    """The compiler writes `artifact://<sha256>`; `eval_examples.doc_key`
    stores the bare digest. Without normalising, every join misses and the set
    scores a flat zero with no error anywhere — the single most expensive way
    this can fail."""
    rows = [{"artifact_ref": f"artifact://{KEY_A}", "total": "1"}]
    assert list(collapse_rows_by_doc(rows, ["total"])) == [KEY_A]


def test_bare_hash_ref_still_works():
    rows = [{"artifact_ref": KEY_A, "total": "1"}]
    assert list(collapse_rows_by_doc(rows, ["total"])) == [KEY_A]


def test_documents_stay_separate():
    rows = [
        {"artifact_ref": KEY_A, "total": "1"},
        {"artifact_ref": KEY_B, "total": "2"},
    ]
    got = collapse_rows_by_doc(rows, ["total"])
    assert got[KEY_A]["total"] == "1"
    assert got[KEY_B]["total"] == "2"


def test_rows_without_a_document_ref_are_dropped():
    """A row with no `artifact_ref` cannot be attributed to a label. Scoring it
    against nothing would silently count as a miss for whichever document
    happened to sort next to it."""
    rows = [{"total": "1"}, {"artifact_ref": KEY_A, "total": "2"}]
    assert list(collapse_rows_by_doc(rows, ["total"])) == [KEY_A]


def test_empty_string_counts_as_null():
    """A model that answers "" has abstained. Treating it as an answer turns a
    correct abstention into a wrong one."""
    rows = [
        {"artifact_ref": KEY_A, "total": ""},
        {"artifact_ref": KEY_A, "total": "1240.50"},
    ]
    assert collapse_rows_by_doc(rows, ["total"])[KEY_A]["total"] == "1240.50"


# ── joining to labels and scoring ────────────────────────────────────────


def test_scores_only_labeled_documents():
    """An unlabeled document in the corpus is not a miss — there is nothing to
    compare it to. Counting it would punish an extractor for the labeler's
    backlog."""
    rows = [
        {"artifact_ref": KEY_A, "total": "1240.50", "vendor": "Acme"},
        {"artifact_ref": KEY_C, "total": "5.00", "vendor": "Nobody"},
    ]
    examples = [_example(KEY_A, {"total": "1240.50", "vendor": "Acme"})]
    result = join_and_score(rows, examples, SPECS)
    assert result["n"] == 1
    assert result["macro_f1"] == 1.0


def test_a_labeled_document_the_run_never_produced_is_a_miss():
    """The opposite case: the label exists, extraction produced nothing. That
    is a silent miss on every field, and must not be quietly skipped — an
    extractor that crashes on half the corpus would otherwise score perfectly
    on the half it managed."""
    examples = [_example(KEY_A, {"total": "1240.50", "vendor": "Acme"})]
    result = join_and_score([], examples, SPECS)
    assert result["n"] == 1
    assert result["macro_f1"] == 0.0
    by_field = {f["name"]: f for f in result["fields"]}
    assert by_field["total"]["fn"] == 1
    assert by_field["total"]["tp"] == 0


def test_formatting_differences_still_match():
    rows = [{"artifact_ref": KEY_A, "total": "$1,240.50", "vendor": "  ACME  "}]
    examples = [_example(KEY_A, {"total": "1240.5", "vendor": "Acme"})]
    result = join_and_score(rows, examples, SPECS)
    assert result["macro_f1"] == 1.0


def test_per_field_breakdown_is_reported():
    rows = [{"artifact_ref": KEY_A, "total": "1240.50", "vendor": "Wrong Co"}]
    examples = [_example(KEY_A, {"total": "1240.50", "vendor": "Acme"})]
    result = join_and_score(rows, examples, SPECS)
    by_field = {f["name"]: f for f in result["fields"]}
    assert by_field["total"]["f1"] == 1.0
    assert by_field["vendor"]["f1"] == 0.0
    # Macro-F1, not micro: one easy field must not carry the score.
    assert result["macro_f1"] == pytest.approx(0.5)


def test_holdout_is_scored_separately():
    """A large train/holdout gap means the prompt was tuned to the eval set.
    It has to be visible, not inferred."""
    rows = [
        {"artifact_ref": KEY_A, "total": "1240.50"},
        {"artifact_ref": KEY_B, "total": "wrong"},
    ]
    examples = [
        _example(KEY_A, {"total": "1240.50"}, split="train"),
        _example(KEY_B, {"total": "77.00"}, split="holdout"),
    ]
    specs = [FieldSpec(name="total", type="numeric")]
    result = join_and_score(rows, examples, specs)
    assert result["n"] == 1
    assert result["macro_f1"] == 1.0
    assert result["holdout"]["n"] == 1
    assert result["holdout"]["macro_f1"] == 0.0


def test_no_holdout_examples_reports_none_not_zero():
    """An unmeasured holdout must never render as a score of 0."""
    rows = [{"artifact_ref": KEY_A, "total": "1240.50"}]
    examples = [_example(KEY_A, {"total": "1240.50"})]
    result = join_and_score(rows, examples, [FieldSpec(name="total", type="numeric")])
    assert result["holdout"] is None


def test_confidence_interval_is_reported_with_n():
    rows = [{"artifact_ref": KEY_A, "total": "1240.50"}]
    examples = [_example(KEY_A, {"total": "1240.50"})]
    result = join_and_score(rows, examples, [FieldSpec(name="total", type="numeric")])
    lo, hi = result["macro_f1_interval"]
    assert 0.0 <= lo <= result["macro_f1"] <= hi <= 1.0
    # n=1 must produce a very wide interval — the UI renders this as "noise".
    assert hi - lo > 0.5


def test_label_source_counts_ride_along():
    """The leaderboard warns when a set is majority judge-labeled. That has to
    travel with the score, not be re-derived at render time from labels that
    may have changed since."""
    rows = [{"artifact_ref": KEY_A, "total": "1"}, {"artifact_ref": KEY_B, "total": "2"}]
    examples = [
        _example(KEY_A, {"total": "1"}, label_source="judge"),
        _example(KEY_B, {"total": "2"}, label_source="human"),
    ]
    result = join_and_score(rows, examples, [FieldSpec(name="total", type="numeric")])
    assert result["label_sources"] == {"judge": 1, "human": 1}


def test_scoring_a_field_the_pipeline_never_produced():
    """The spec declares `vendor`; the structure step doesn't emit it. Every
    document is then a silent miss on that field — which is the truth, and is
    exactly what the per-field drill-down needs to show."""
    rows = [{"artifact_ref": KEY_A, "total": "1240.50"}]
    examples = [_example(KEY_A, {"total": "1240.50", "vendor": "Acme"})]
    result = join_and_score(rows, examples, SPECS)
    by_field = {f["name"]: f for f in result["fields"]}
    assert by_field["vendor"]["fn"] == 1
    assert by_field["vendor"]["recall"] == 0.0


def test_empty_corpus_scores_nothing_rather_than_perfectly():
    result = join_and_score([], [], SPECS)
    assert result["n"] == 0
    assert result["macro_f1"] is None


def test_failures_are_collected_for_the_drill_down():
    rows = [{"artifact_ref": KEY_A, "total": "1204.50", "vendor": "Acme"}]
    examples = [_example(KEY_A, {"total": "1240.50", "vendor": "Acme"})]
    result = join_and_score(rows, examples, SPECS, collect_failures=True)
    fails = result["failures"]
    assert len(fails) == 1
    assert fails[0]["doc_key"] == KEY_A
    assert fails[0]["field"] == "total"
    assert fails[0]["expected"] == "1240.50"
    assert fails[0]["actual"] == "1204.50"
