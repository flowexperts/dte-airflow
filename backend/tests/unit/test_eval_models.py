"""Model-level rules for the eval harness storage (plan 051, phase 1).

These guard the three things that make an eval set trustworthy rather than
merely present: labels are keyed by document *content*, a label always
declares where it came from, and the field specs the run scores against are
the same shape the scorer consumes.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from dte.evals.scoring import FieldSpec
from dte.models.eval import EvalExampleBase, EvalSetBase


def test_eval_set_requires_at_least_one_field_spec():
    with pytest.raises(ValidationError):
        EvalSetBase(id="es1", name="Invoices", source_id="docs", field_specs=[])


def test_field_specs_feed_the_scorer_unchanged():
    """The task definition and the scoring definition are the same thing.
    If this drifts, a set scores against a spec it was not labeled for."""
    es = EvalSetBase(
        id="es1",
        name="Invoices",
        source_id="docs",
        field_specs=[
            {"name": "total", "type": "numeric", "comparator": {"rel_tol": 0.01}},
            {"name": "vendor", "type": "string", "description": "who billed us"},
        ],
    )
    specs = es.to_field_specs()
    assert [s.name for s in specs] == ["total", "vendor"]
    assert all(isinstance(s, FieldSpec) for s in specs)
    assert specs[0].comparator == {"rel_tol": 0.01}
    # `description` is for the extractor, not the scorer — it must not leak in.
    assert specs[1].comparator == {}


def test_duplicate_field_names_rejected():
    with pytest.raises(ValidationError):
        EvalSetBase(
            id="es1",
            name="Invoices",
            source_id="docs",
            field_specs=[
                {"name": "total", "type": "numeric"},
                {"name": "total", "type": "string"},
            ],
        )


def test_unknown_comparator_type_rejected_at_save_not_at_score():
    """A bad comparator must fail when the set is created, not silently at the
    end of a paid sweep."""
    with pytest.raises(ValidationError):
        EvalSetBase(
            id="es1",
            name="Invoices",
            source_id="docs",
            field_specs=[{"name": "total", "type": "not_a_comparator"}],
        )


def test_eval_set_blank_id_means_generate():
    es = EvalSetBase(
        id="", name="Invoices", source_id="docs",
        field_specs=[{"name": "total", "type": "numeric"}],
    )
    assert es.id


def test_labels_version_defaults_to_one():
    es = EvalSetBase(
        id="es1", name="Invoices", source_id="docs",
        field_specs=[{"name": "total", "type": "numeric"}],
    )
    assert es.labels_version == 1


def test_example_doc_key_must_be_a_sha256():
    """`doc_key` is the artifact store's key. A path or filename here would
    join against nothing and produce a permanently empty score."""
    with pytest.raises(ValidationError):
        EvalExampleBase(
            id="ex1", eval_set_id="es1", doc_key="invoices/march.pdf", labels={}
        )


def test_example_label_source_is_required_and_constrained():
    key = "a" * 64
    ok = EvalExampleBase(
        id="ex1", eval_set_id="es1", doc_key=key,
        labels={"total": "1240.50"}, label_source="human",
    )
    assert ok.label_source == "human"
    assert ok.split == "train"

    with pytest.raises(ValidationError):
        EvalExampleBase(
            id="ex2", eval_set_id="es1", doc_key=key, labels={},
            label_source="vibes",
        )


def test_example_split_constrained_to_train_or_holdout():
    with pytest.raises(ValidationError):
        EvalExampleBase(
            id="ex1", eval_set_id="es1", doc_key="b" * 64, labels={},
            label_source="human", split="test",
        )


def test_doc_key_is_case_normalised():
    """sha256 hex is case-insensitive; the UNIQUE constraint is not."""
    ex = EvalExampleBase(
        id="ex1", eval_set_id="es1", doc_key=("A" * 64), labels={},
        label_source="human",
    )
    assert ex.doc_key == "a" * 64
