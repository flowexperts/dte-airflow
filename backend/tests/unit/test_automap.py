"""The one check the matcher needs: names, types, and no accidental network."""

import pytest

from dte.automap import Field, automap


def _by_dest(result):
    return {m.dest: m for m in result.matches}


def test_exact_match_ignores_case_and_separators():
    r = automap([Field("customer_id", "int64")], [Field("CustomerID", "int64")], use_llm=False)
    m = _by_dest(r)["CustomerID"]
    assert (m.source, m.confidence, m.via, m.warning) == ("customer_id", 1.0, "exact", None)
    assert r.unmatched_source == []


def test_fuzzy_match_below_exact():
    r = automap([Field("ship_date", "date")], [Field("shipping_date", "date")], use_llm=False)
    m = _by_dest(r)["shipping_date"]
    assert m.source == "ship_date"
    assert m.via == "fuzzy"
    assert 0.8 <= m.confidence < 1.0


def test_type_mismatch_is_flagged_not_dropped():
    r = automap([Field("total", "int64")], [Field("total", "string")], use_llm=False)
    m = _by_dest(r)["total"]
    assert m.source == "total"            # still offered
    assert m.warning == "int64 → string"
    assert m.confidence == 0.5            # capped, so it is not pre-selected


def test_unmatched_columns_reported_both_ways():
    r = automap([Field("legacy_code", "string")], [Field("tax_region", "string")], use_llm=False)
    m = _by_dest(r)["tax_region"]
    assert (m.source, m.via, m.confidence) == (None, None, 0.0)
    assert r.unmatched_source == ["legacy_code"]


def test_a_source_column_is_claimed_once():
    r = automap(
        [Field("name", "string")],
        [Field("name", "string"), Field("names", "string")],
        use_llm=False,
    )
    by = _by_dest(r)
    assert by["name"].source == "name"    # exact wins
    assert by["names"].source is None     # fuzzy cannot re-use it


def test_use_llm_false_makes_no_network_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-be-read")
    monkeypatch.setattr(
        "dte.automap._llm_match",
        lambda *a, **k: pytest.fail("LLM pass ran with use_llm=False"),
    )
    r = automap([Field("dob", "date")], [Field("birth_date", "date")], use_llm=False)
    assert r.llm_error is None
    assert _by_dest(r)["birth_date"].source is None


def test_llm_failure_keeps_the_heuristic_result(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = automap(
        [Field("customer_id", "int64"), Field("dob", "date")],
        [Field("CustomerID", "int64"), Field("birth_date", "date")],
    )
    assert "ANTHROPIC_API_KEY" in r.llm_error
    assert _by_dest(r)["CustomerID"].source == "customer_id"


def test_llm_pass_cannot_invent_or_steal_columns(monkeypatch):
    monkeypatch.setattr(
        "dte.automap._llm_match",
        lambda s, d: {"birth_date": "dob", "CustomerID": "dob", "nope": "dob"},
    )
    r = automap(
        [Field("customer_id", "int64"), Field("dob", "date")],
        [Field("CustomerID", "int64"), Field("birth_date", "date")],
    )
    by = _by_dest(r)
    assert (by["birth_date"].source, by["birth_date"].via) == ("dob", "llm")
    assert by["CustomerID"].via == "exact"   # not overwritten
    assert "nope" not in by                  # invented dest discarded
    assert r.unmatched_source == []
