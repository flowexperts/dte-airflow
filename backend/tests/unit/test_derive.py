"""Deriving an eval set's `field_specs` from a pipeline's structure step.

The bug this removes: a user had to type their field list twice — once in
the structure step's `model.fields`, once in the eval set's `field_specs` —
under a UI warning stating that a mismatch "won't error; it scores zero on
every document." Two hand-maintained copies of the same list, where drift
between them is silent and presents as a broken extractor.

The pipeline is the single definition. Derivation is one-directional
(structure step → eval set, never back), because two-way sync between two
similar-but-unequal shapes is exactly how the drift would return.
"""
from __future__ import annotations

import pytest

from dte.evals.comparators import COMPARATOR_TYPES
from dte.evals.derive import eval_set_fingerprint, field_specs_from_structure


def _step(fields: list[dict], **kw) -> dict:
    return {
        "op": "structure",
        "input_field": "content",
        "provider": kw.pop("provider", "claude"),
        "model": {"fields": fields, "instructions": kw.pop("instructions", "")},
        "params": {},
        "on_error": "null",
        **kw,
    }


class TestTypeMap:
    """Structure types are a strict subset of comparator types, but the
    names differ where the concepts differ."""

    @pytest.mark.parametrize(
        "structure_type,eval_type",
        [
            ("int", "numeric"),
            ("float", "numeric"),
            ("string", "string"),
            ("boolean", "boolean"),
            ("date", "date"),
            ("timestamp", "timestamp"),
        ],
    )
    def test_maps_each_structure_type(self, structure_type, eval_type):
        specs = field_specs_from_structure(_step([{"name": "f", "type": structure_type}]))
        assert specs[0]["type"] == eval_type

    def test_every_derived_type_is_a_real_comparator(self):
        # A derived type the scorer does not recognise would 422 the eval-set
        # create with a message about a field the user never typed.
        every = [{"name": f"f{i}", "type": t} for i, t in enumerate(
            ["string", "int", "float", "boolean", "date", "timestamp"]
        )]
        for spec in field_specs_from_structure(_step(every)):
            assert spec["type"] in COMPARATOR_TYPES

    def test_unknown_type_falls_back_to_string(self):
        # Forward-compatible: a structure type added later should degrade to
        # the most forgiving comparator rather than raise mid-wizard.
        specs = field_specs_from_structure(_step([{"name": "f", "type": "geo_point"}]))
        assert specs[0]["type"] == "string"

    def test_missing_type_defaults_to_string(self):
        # `type` has a default on DataModelField; a raw dict may omit it.
        specs = field_specs_from_structure(_step([{"name": "f"}]))
        assert specs[0]["type"] == "string"


class TestWhatCarriesAcross:
    def test_name_and_description_carry(self):
        specs = field_specs_from_structure(
            _step([{"name": "invoice_total", "type": "float", "description": "grand total"}])
        )
        assert specs[0]["name"] == "invoice_total"
        assert specs[0]["description"] == "grand total"

    def test_extraction_only_keys_are_dropped(self):
        # `pattern`, `required` and `examples` steer extraction. None of them
        # mean anything to a comparator, and carrying them would imply the
        # eval set has an opinion about how the value was obtained.
        specs = field_specs_from_structure(
            _step([{
                "name": "total",
                "type": "float",
                "pattern": r"Total:\s*\$?([\d,.]+)",
                "required": True,
                "examples": ["1240.50"],
            }])
        )
        assert set(specs[0]) <= {"name", "type", "description", "comparator"}

    def test_numeric_gets_a_comparator_block(self):
        # Numeric comparison is the one place a default tolerance is
        # load-bearing: $1,240.50 must match 1240.5, and 1240.50 must not
        # match 1204.50.
        specs = field_specs_from_structure(_step([{"name": "total", "type": "float"}]))
        assert specs[0]["comparator"] == {"rel_tol": 0.0}

    def test_string_gets_no_comparator_block(self):
        specs = field_specs_from_structure(_step([{"name": "vendor", "type": "string"}]))
        assert "comparator" not in specs[0]

    def test_llm_judge_is_never_derived(self):
        # A judge costs money on every row and flatters an extractor from its
        # own family. It must be an explicit choice, never something a wizard
        # turned on for you.
        every = [{"name": f"f{i}", "type": t} for i, t in enumerate(
            ["string", "int", "float", "boolean", "date", "timestamp", "unknown"]
        )]
        for spec in field_specs_from_structure(_step(every)):
            assert spec["type"] != "llm_judge"

    def test_field_order_is_preserved(self):
        specs = field_specs_from_structure(
            _step([{"name": "c"}, {"name": "a"}, {"name": "b"}])
        )
        assert [s["name"] for s in specs] == ["c", "a", "b"]


class TestRejections:
    def test_no_structure_step_raises(self):
        with pytest.raises(ValueError, match="structure step"):
            field_specs_from_structure({"op": "extract"})

    def test_no_fields_raises(self):
        with pytest.raises(ValueError, match="at least one field"):
            field_specs_from_structure(_step([]))

    def test_accepts_a_step_whose_model_is_a_pydantic_object(self):
        # Steps arrive as dicts off the wire but as model objects when read
        # back through a parsed Pipeline. Both must work or the wizard
        # succeeds on create and fails on re-open.
        from dte.models.pipeline import StructureStep

        step = StructureStep.model_validate(_step([{"name": "total", "type": "float"}]))
        specs = field_specs_from_structure(step.model_dump())
        assert specs[0]["name"] == "total"


class TestFingerprint:
    """Idempotence: clicking Compare twice must reuse one eval set rather
    than accumulate a new one per click, each with its own labels."""

    def test_same_source_and_fields_gives_same_fingerprint(self):
        specs = field_specs_from_structure(_step([{"name": "total", "type": "float"}]))
        assert eval_set_fingerprint("docs", specs) == eval_set_fingerprint("docs", specs)

    def test_different_source_differs(self):
        specs = field_specs_from_structure(_step([{"name": "total", "type": "float"}]))
        assert eval_set_fingerprint("a", specs) != eval_set_fingerprint("b", specs)

    def test_field_order_does_not_change_the_fingerprint(self):
        # Reordering fields in the builder is a cosmetic edit. If it minted a
        # new eval set, the user would silently lose every label they had.
        a = field_specs_from_structure(_step([{"name": "x"}, {"name": "y"}]))
        b = field_specs_from_structure(_step([{"name": "y"}, {"name": "x"}]))
        assert eval_set_fingerprint("docs", a) == eval_set_fingerprint("docs", b)

    def test_adding_a_field_changes_the_fingerprint(self):
        a = field_specs_from_structure(_step([{"name": "x"}]))
        b = field_specs_from_structure(_step([{"name": "x"}, {"name": "y"}]))
        assert eval_set_fingerprint("docs", a) != eval_set_fingerprint("docs", b)

    def test_changing_a_type_changes_the_fingerprint(self):
        # The comparator changed, so prior scores are not comparable.
        a = field_specs_from_structure(_step([{"name": "x", "type": "string"}]))
        b = field_specs_from_structure(_step([{"name": "x", "type": "float"}]))
        assert eval_set_fingerprint("docs", a) != eval_set_fingerprint("docs", b)

    def test_description_does_not_change_the_fingerprint(self):
        # Descriptions steer the model, not the scoring. Rewording a prompt
        # hint must not orphan the corpus it was labelled against.
        a = field_specs_from_structure(_step([{"name": "x", "description": "one"}]))
        b = field_specs_from_structure(_step([{"name": "x", "description": "two"}]))
        assert eval_set_fingerprint("docs", a) == eval_set_fingerprint("docs", b)

    def test_fingerprint_is_a_short_hex_slug(self):
        specs = field_specs_from_structure(_step([{"name": "x"}]))
        fp = eval_set_fingerprint("docs", specs)
        assert len(fp) == 12 and all(c in "0123456789abcdef" for c in fp)
