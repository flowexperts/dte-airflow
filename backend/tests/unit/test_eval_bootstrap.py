"""Consensus bootstrap (plan 051 phase 3, task 12).

The harness's real enemy is an empty eval set: everyone builds the
scoreboard, discovers that hand-labeling 200 PDFs is nobody's Tuesday, and
the thing sits unused. Consensus is the answer — run several cheap variants
and keep only what they unanimously agree on — so the correctness of
"agree" is the whole feature.

Two rules do the load-bearing work here:

* **Agreement uses the eval set's own comparators.** `$1,240.50` and
  `1240.50` are the same answer; treating them as a disagreement would push
  most of a currency corpus into the review queue and destroy the time
  saving the feature exists to deliver.
* **Unanimity is required, and null is not a vote.** Two variants that both
  abstain have not agreed on anything.
"""
from __future__ import annotations

import pytest

from dte.evals.bootstrap import consensus
from dte.evals.scoring import FieldSpec

SPECS = [
    FieldSpec(name="invoice_no", type="string"),
    FieldSpec(name="total", type="numeric", comparator={"rel_tol": 0.001}),
]

DOC_A = "a" * 64
DOC_B = "b" * 64


def _rows(*pairs):
    return [
        {"artifact_ref": f"artifact://{key}", **fields} for key, fields in pairs
    ]


def test_unanimous_documents_become_consensus_labels():
    result = consensus(
        {
            "v1": _rows((DOC_A, {"invoice_no": "INV-1", "total": "1240.50"})),
            "v2": _rows((DOC_A, {"invoice_no": "INV-1", "total": "1240.50"})),
        },
        SPECS,
    )
    assert [p["doc_key"] for p in result["agreed"]] == [DOC_A]
    assert result["agreed"][0]["labels"] == {"invoice_no": "INV-1", "total": "1240.50"}
    assert result["disagreed"] == []


def test_formatting_differences_are_agreement_not_disagreement():
    """The comparator, not string equality, decides. Without this a corpus of
    currency values lands almost entirely in the review queue and consensus
    saves nobody any time."""
    result = consensus(
        {
            "v1": _rows((DOC_A, {"invoice_no": "INV-1", "total": "$1,240.50"})),
            "v2": _rows((DOC_A, {"invoice_no": "INV-1", "total": "1240.5"})),
        },
        SPECS,
    )
    assert len(result["agreed"]) == 1
    assert result["disagreed"] == []


def test_a_real_disagreement_goes_to_review_with_every_candidate():
    result = consensus(
        {
            "v1": _rows((DOC_A, {"invoice_no": "INV-1", "total": "1240.50"})),
            "v2": _rows((DOC_A, {"invoice_no": "INV-1", "total": "1204.50"})),
        },
        SPECS,
    )
    assert result["agreed"] == []
    (item,) = result["disagreed"]
    assert item["doc_key"] == DOC_A
    # The reviewer needs to see what each variant said — that is the entire
    # value of routing it to a human rather than picking one arbitrarily.
    assert item["candidates"]["total"] == {"v1": "1240.50", "v2": "1204.50"}
    # A field they *did* agree on is still reported, so the human only has to
    # adjudicate the contested one.
    assert item["agreed_fields"] == {"invoice_no": "INV-1"}


def test_unanimous_abstention_is_not_consensus():
    """Two variants returning nothing have not agreed on a value. Writing
    null as ground truth would teach the corpus that the right answer is
    'no answer', and every extractor that abstains would then score well."""
    result = consensus(
        {
            "v1": _rows((DOC_A, {"invoice_no": None, "total": None})),
            "v2": _rows((DOC_A, {"invoice_no": None, "total": None})),
        },
        SPECS,
    )
    assert result["agreed"] == []
    assert [d["doc_key"] for d in result["disagreed"]] == [DOC_A]


def test_a_document_missing_from_one_variant_is_a_disagreement():
    result = consensus(
        {
            "v1": _rows(
                (DOC_A, {"invoice_no": "INV-1", "total": "1240.50"}),
                (DOC_B, {"invoice_no": "INV-2", "total": "10"}),
            ),
            "v2": _rows((DOC_A, {"invoice_no": "INV-1", "total": "1240.50"})),
        },
        SPECS,
    )
    assert [p["doc_key"] for p in result["agreed"]] == [DOC_A]
    assert [d["doc_key"] for d in result["disagreed"]] == [DOC_B]


def test_a_single_variant_can_never_reach_consensus():
    """One variant agreeing with itself is not evidence. Allowing it would
    turn bootstrap into 'trust this model', tagged as consensus."""
    with pytest.raises(ValueError, match="at least two"):
        consensus({"v1": _rows((DOC_A, {"invoice_no": "INV-1"}))}, SPECS)


def test_shared_provider_across_variants_blocks_auto_accept():
    """Three prompts against the same model share its blind spots; unanimity
    among them measures the prompt, not the truth. The result still computes
    — it is offered for review — but `auto_accept` is refused."""
    result = consensus(
        {
            "v1": _rows((DOC_A, {"invoice_no": "INV-1"})),
            "v2": _rows((DOC_A, {"invoice_no": "INV-1"})),
        },
        [FieldSpec(name="invoice_no", type="string")],
        providers={"v1": "claude", "v2": "claude"},
    )
    assert result["auto_accept"] is False
    assert "provider" in result["warning"].lower()
    assert len(result["agreed"]) == 1


def test_distinct_providers_permit_auto_accept():
    result = consensus(
        {
            "v1": _rows((DOC_A, {"invoice_no": "INV-1"})),
            "v2": _rows((DOC_A, {"invoice_no": "INV-1"})),
        },
        [FieldSpec(name="invoice_no", type="string")],
        providers={"v1": "claude", "v2": "openai"},
    )
    assert result["auto_accept"] is True
    assert result["warning"] is None
