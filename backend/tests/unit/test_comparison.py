"""Comparing configs before anyone has labelled anything (plan 053).

Plan 051's leaderboard opens on "No comparable runs yet." That is the
wrong default and it is why the harness sat empty: it demands ground truth
before it will show you anything, and hand-labelling a corpus is nobody's
Tuesday.

But a sweep with no labels already answers most of the question. Where do
the providers disagree? What did each cost? How often did each abstain?
None of that needs a label, and the documents where they disagree are
simultaneously the review queue — so the label-free view is also the
fastest path *to* labels.

Scores are therefore an addition to this payload when labels exist, never
a precondition for producing it.
"""
from __future__ import annotations

import pytest

from dte.evals.comparison import build_comparison
from dte.evals.scoring import FieldSpec


SPECS = [
    FieldSpec(name="total", type="numeric", comparator={"rel_tol": 0.0}),
    FieldSpec(name="vendor", type="string", comparator={}),
]


def _cell(label, values, **kw):
    """One sweep cell: its identity, its rows, and how it performed."""
    return {
        "cell_id": label,
        "pipeline_id": f"p__{label}",
        "run_id": f"r__{label}",
        "status": kw.pop("status", "completed"),
        "cell": kw.pop("cell", {"provider": label}),
        "rows": [
            {"artifact_ref": f"artifact://{k}", **v} for k, v in values.items()
        ],
        "scores": kw.pop("scores", None),
        "throughput": kw.pop("throughput", {}),
    }


class TestNoLabelsRequired:
    def test_builds_without_any_labels(self):
        out = build_comparison(
            [
                _cell("claude", {"a" * 64: {"total": "1240.50", "vendor": "Acme"}}),
                _cell("openai", {"a" * 64: {"total": "1240.50", "vendor": "Acme"}}),
            ],
            SPECS,
        )
        assert out["labels"]["total"] == 0
        assert len(out["documents"]) == 1

    def test_cells_carry_no_score_keys_when_unlabelled(self):
        # Absent, not zero. A cell that was never scored and a cell that
        # scored zero are opposite situations; rendering them alike is how a
        # working extractor gets mistaken for a broken one.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1"}}),
             _cell("regex", {"a" * 64: {"total": "1"}})],
            SPECS,
        )
        for cell in out["cells"]:
            assert cell.get("macro_f1") is None

    def test_single_cell_is_allowed(self):
        # Agreement is undefined with one config, but cost and null-rate are
        # not — and someone may open the page while cell two is still running.
        out = build_comparison([_cell("claude", {"a" * 64: {"total": "1"}})], SPECS)
        assert len(out["cells"]) == 1
        assert out["fields"][0]["agreement_rate"] is None


class TestAgreement:
    def test_agreement_uses_comparators_not_string_equality(self):
        # $1,240.50 and 1240.5 are the same answer. Comparing them literally
        # would route most of a currency corpus into the disagreement queue
        # and delete the time saving the queue exists to produce.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "$1,240.50", "vendor": "Acme"}}),
             _cell("openai", {"a" * 64: {"total": "1240.5", "vendor": "Acme"}})],
            SPECS,
        )
        total = next(f for f in out["fields"] if f["name"] == "total")
        assert total["agreement_rate"] == 1.0
        assert total["disagreement_count"] == 0

    def test_genuine_disagreement_is_counted(self):
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1240.50", "vendor": "Acme"}}),
             _cell("openai", {"a" * 64: {"total": "1204.50", "vendor": "Acme"}})],
            SPECS,
        )
        total = next(f for f in out["fields"] if f["name"] == "total")
        assert total["agreement_rate"] == 0.0
        assert total["disagreement_count"] == 1

    def test_all_null_is_not_agreement(self):
        # Variants that all abstained agreed on nothing. Counting it as
        # agreement would let a corpus of silence look unanimous — and if
        # those were then accepted as labels, every extractor that abstains
        # would score well, which is the failure scoring splits tn from fn
        # to avoid.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": None, "vendor": "Acme"}}),
             _cell("openai", {"a" * 64: {"total": None, "vendor": "Acme"}})],
            SPECS,
        )
        total = next(f for f in out["fields"] if f["name"] == "total")
        assert total["agreement_rate"] == 0.0

    def test_a_document_one_cell_never_produced_is_a_disagreement(self):
        # Union, not intersection — matching bootstrap. A document one
        # config silently dropped is exactly what you want to see.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1", "vendor": "A"},
                              "b" * 64: {"total": "2", "vendor": "B"}}),
             _cell("openai", {"a" * 64: {"total": "1", "vendor": "A"}})],
            SPECS,
        )
        assert len(out["documents"]) == 2
        missing = next(d for d in out["documents"] if d["doc_key"] == "b" * 64)
        assert missing["agrees"] is False
        assert sum(1 for d in out["documents"] if not d["agrees"]) == 1

    def test_document_agrees_only_when_every_field_agrees(self):
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1", "vendor": "Acme"}}),
             _cell("openai", {"a" * 64: {"total": "1", "vendor": "Globex"}})],
            SPECS,
        )
        assert out["documents"][0]["agrees"] is False

    def test_agreed_unlabelled_count_drives_the_accept_button(self):
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1", "vendor": "A"},
                              "b" * 64: {"total": "2", "vendor": "B"}}),
             _cell("openai", {"a" * 64: {"total": "1", "vendor": "A"},
                              "b" * 64: {"total": "9", "vendor": "B"}})],
            SPECS,
        )
        assert out["labels"]["agreed_unlabeled"] == 1

    def test_already_labelled_documents_are_not_offered_again(self):
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1", "vendor": "A"}}),
             _cell("openai", {"a" * 64: {"total": "1", "vendor": "A"}})],
            SPECS,
            labelled_doc_keys={"a" * 64},
        )
        assert out["labels"]["total"] == 1
        assert out["labels"]["agreed_unlabeled"] == 0


class TestPerDocumentValues:
    def test_each_document_carries_every_cells_value(self):
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1", "vendor": "A"}}),
             _cell("openai", {"a" * 64: {"total": "2", "vendor": "A"}})],
            SPECS,
        )
        doc = out["documents"][0]
        assert doc["values"]["claude"]["total"] == "1"
        assert doc["values"]["openai"]["total"] == "2"

    def test_a_missing_document_reads_as_null_not_absent(self):
        # The grid renders one column per cell. An absent key would collapse
        # the row and misalign every column after it.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1"}}),
             _cell("openai", {})],
            SPECS,
        )
        assert out["documents"][0]["values"]["openai"] == {"total": None, "vendor": None}

    def test_documents_are_ordered_disagreements_first(self):
        # The disagreements are the reason to open this page. Burying them
        # under a hundred agreeing rows makes the page useless at real corpus
        # sizes.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1", "vendor": "A"},
                              "b" * 64: {"total": "2", "vendor": "B"}}),
             _cell("openai", {"a" * 64: {"total": "1", "vendor": "A"},
                              "b" * 64: {"total": "9", "vendor": "B"}})],
            SPECS,
        )
        assert out["documents"][0]["doc_key"] == "b" * 64
        assert out["documents"][0]["agrees"] is False

    def test_doc_ref_is_carried_for_the_inspector(self):
        cell = _cell("claude", {"a" * 64: {"total": "1"}})
        cell["rows"][0]["path"] = "/docs/inv-1.pdf"
        out = build_comparison([cell, _cell("openai", {})], SPECS)
        assert out["documents"][0]["doc_ref"] == "/docs/inv-1.pdf"


class TestCellMetrics:
    def test_null_rate_is_per_cell(self):
        # The headline signal when comparing a cheap config to an expensive
        # one: abstention is not the same as being wrong, and a config that
        # answers nothing must not look clean.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1", "vendor": "A"},
                              "b" * 64: {"total": "2", "vendor": "B"}}),
             _cell("regex", {"a" * 64: {"total": None, "vendor": None},
                             "b" * 64: {"total": "2", "vendor": None}})],
            SPECS,
        )
        by_id = {c["cell_id"]: c for c in out["cells"]}
        assert by_id["claude"]["null_rate"] == 0.0
        assert by_id["regex"]["null_rate"] == 0.75

    def test_throughput_is_passed_through(self):
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1"}},
                   throughput={"cost_usd": 0.42, "latency_p95_ms": 900,
                               "cache_hit_rate": 0.5}),
             _cell("regex", {"a" * 64: {"total": "1"}},
                   throughput={"cost_usd": 0.0, "latency_p95_ms": None,
                               "cache_hit_rate": 1.0})],
            SPECS,
        )
        by_id = {c["cell_id"]: c for c in out["cells"]}
        assert by_id["claude"]["cost_usd"] == 0.42
        assert by_id["regex"]["cost_usd"] == 0.0

    def test_unknown_cost_stays_none(self):
        # cost.py's rule: an unknown price is None, never a guess. A
        # fabricated figure gets budgeted against and is wrong invisibly.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1"}}, throughput={"cost_usd": None}),
             _cell("openai", {"a" * 64: {"total": "1"}})],
            SPECS,
        )
        assert all(c["cost_usd"] is None for c in out["cells"])

    def test_cell_config_is_carried_for_labelling_the_column(self):
        out = build_comparison(
            [_cell("a", {"x" * 64: {"total": "1"}}, cell={"provider": "claude"}),
             _cell("b", {"x" * 64: {"total": "1"}}, cell={"provider": "openai"})],
            SPECS,
        )
        assert out["cells"][0]["cell"] == {"provider": "claude"}


class TestScoresWhenLabelsExist:
    def _scored(self, f1, n=40):
        return {"macro_f1": f1, "macro_f1_interval": [f1 - 0.05, f1 + 0.05], "n": n}

    def test_scores_surface_when_present(self):
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1"}}, scores=self._scored(0.91)),
             _cell("openai", {"a" * 64: {"total": "1"}}, scores=self._scored(0.72))],
            SPECS,
        )
        by_id = {c["cell_id"]: c for c in out["cells"]}
        assert by_id["claude"]["macro_f1"] == 0.91
        assert by_id["claude"]["n"] == 40

    def test_clear_winner_is_ranked(self):
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1"}}, scores=self._scored(0.95)),
             _cell("openai", {"a" * 64: {"total": "1"}}, scores=self._scored(0.40))],
            SPECS,
        )
        by_id = {c["cell_id"]: c for c in out["cells"]}
        assert by_id["claude"]["rank"] == 1
        assert by_id["openai"]["rank"] == 2
        assert by_id["claude"]["tied_with_leader"] is False

    def test_overlapping_intervals_render_as_tied(self):
        # The plan-051 honesty rule, carried into this surface. Declaring a
        # winner on noise is worse than declaring none: it sends someone off
        # to ship a config that is not actually better.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1"}}, scores=self._scored(0.90)),
             _cell("openai", {"a" * 64: {"total": "1"}}, scores=self._scored(0.88))],
            SPECS,
        )
        for cell in out["cells"]:
            assert cell["rank"] == 1
            assert cell["tied_with_leader"] is True

    def test_a_failed_cell_is_present_but_unranked(self):
        # Dropping it would leave the user wondering which config vanished.
        out = build_comparison(
            [_cell("claude", {"a" * 64: {"total": "1"}}, scores=self._scored(0.9)),
             _cell("openai", {}, status="failed")],
            SPECS,
        )
        by_id = {c["cell_id"]: c for c in out["cells"]}
        assert by_id["openai"]["status"] == "failed"
        assert by_id["openai"].get("rank") is None


class TestRejections:
    def test_no_cells_raises(self):
        with pytest.raises(ValueError, match="no cells"):
            build_comparison([], SPECS)

    def test_no_specs_raises(self):
        with pytest.raises(ValueError, match="field"):
            build_comparison([_cell("claude", {"a" * 64: {}})], [])
