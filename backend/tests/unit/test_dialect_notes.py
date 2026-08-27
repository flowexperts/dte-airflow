"""Cross-engine divergence notes — plan 062.

Every case here was measured by transpiling the expression to Postgres and
running it; see the plan for the raw results.
"""
from __future__ import annotations

import pytest

from dte.compiler.dialect_notes import execution_dialect_of, notes_for, transpile_fragment


def test_date_diff_years_is_flagged_on_postgres():
    notes = notes_for("date_diff('year', dob, current_date)", "postgres")
    assert [n.code for n in notes] == ["date_diff_unit_semantics"]
    assert "duckdb" in notes[0].message.lower()


def test_date_diff_days_is_not_flagged():
    """Only year/month diverge — a day count is a day count everywhere."""
    assert notes_for("date_diff('day', a, b)", "postgres") == []


def test_try_cast_is_flagged_on_postgres():
    assert [n.code for n in notes_for("try_cast(s as integer)", "postgres")] == [
        "try_cast_becomes_cast"
    ]


def test_ordinary_expressions_are_not_flagged():
    for expr in ["upper(s)", "split_part(s, ',', 1)", "date_trunc('month', ts)",
                 "last_day(ts)", "round(x, 2)", "coalesce(s, 'x')"]:
        assert notes_for(expr, "postgres") == [], expr


def test_nothing_is_flagged_on_duckdb():
    """DuckDB is the dialect the fragment is written in — nothing to diverge from."""
    assert notes_for("date_diff('year', a, b)", "duckdb") == []
    assert notes_for("try_cast(s as int)", "duckdb") == []


def test_unparseable_expression_yields_no_notes_and_does_not_raise():
    """A half-typed expression must never blow up the editor's feedback."""
    assert notes_for("date_diff('year',", "postgres") == []


def test_notes_match_the_call_not_the_substring():
    """`date_diff` inside a column name is not a call to date_diff."""
    assert notes_for("my_date_diff_col + 1", "postgres") == []


def test_transpile_fragment_rewrites_for_the_target():
    out = transpile_fragment("date_diff('year', dob, current_date)", "postgres")
    assert "AGE(" in out.upper()


def test_transpile_fragment_returns_none_when_unchanged():
    """Nothing to show the user when the target receives what they typed."""
    assert transpile_fragment("upper(s)", "postgres") is None
    assert transpile_fragment("upper(s)", "duckdb") is None


def test_transpile_fragment_survives_a_half_typed_expression():
    assert transpile_fragment("upper(", "postgres") is None


@pytest.mark.parametrize("expr", ["", "   "])
def test_blank_expression_is_inert(expr):
    assert notes_for(expr, "postgres") == []
    assert transpile_fragment(expr, "postgres") is None


@pytest.mark.parametrize("step,expected", [
    ({"op": "filter", "expr": "a > 1"}, "a > 1"),
    ({"op": "check", "expr": "a IS NOT NULL"}, "a IS NOT NULL"),
    ({"op": "map", "mode": "expression", "expr": "a + 1"}, "a + 1"),
    ({"op": "map", "mode": "calculation", "expr": "a * 2"}, "a * 2"),
    # No SQL in these: a lookup map is a table join, case is structured.
    ({"op": "map", "mode": "lookup", "field": "a", "lookup_id": "l"}, None),
    ({"op": "case", "output_field": "x", "branches": []}, None),
    ({"op": "rename", "mappings": {}}, None),
    ({"op": "filter", "expr": "   "}, None),
    ({"op": "filter"}, None),
])
def test_raw_sql_fragment(step, expected):
    from dte.compiler.dialect_notes import raw_sql_fragment
    assert raw_sql_fragment(step) == expected


# --- date_diff unit semantics, measured per dialect (plan 063) -------------
# The recipe picker offers every unit, so every unit's transpilation was
# measured. Two dialects drop the unit on the floor and return days.


def test_date_diff_weeks_returns_days_on_sqlite():
    notes = notes_for("date_diff('week', a, b)", "sqlite")
    assert [n.code for n in notes] == ["date_diff_unit_semantics"]
    assert "days" in notes[0].message


def test_date_diff_every_unit_returns_days_on_mysql():
    for unit in ("week", "month", "quarter", "year"):
        assert notes_for(f"date_diff('{unit}', a, b)", "mysql"), unit


def test_date_diff_days_is_exact_on_mysql():
    """MySQL's DATEDIFF is days, so a day-unit call is the one honest case."""
    assert notes_for("date_diff('day', a, b)", "mysql") == []


def test_date_diff_months_is_approximate_on_sqlite():
    notes = notes_for("date_diff('month', a, b)", "sqlite")
    assert "30" in notes[0].message


def test_date_diff_quarters_flagged_on_postgres():
    assert notes_for("date_diff('quarter', a, b)", "postgres")
