"""Cross-engine divergences in raw-SQL fragments — plan 062.

Raw SQL now reaches every backend: `table.alias(n).sql(fragment,
dialect="duckdb")` transpiles the user's DuckDB-dialect fragment through
sqlglot to whatever the source's own backend speaks. Reach is solved.
*Meaning* is not, and that is what this module reports.

Three outcomes when a fragment is transpiled, measured by running 55
expressions against a live Postgres:

1. Rewritten correctly (51 of 55) — `strftime` → `TO_CHAR`,
   `regexp_matches` → `~`, `ifnull` → `COALESCE`.
2. Rejected by the target (4) — `datepart`, `contains`, `string_split`,
   `len(array)`. Loud: the database says so itself, and its message is
   better copy than anything written here, so nothing in this module tries
   to predict them.
3. **Accepted, but meaning something else.** Silent, and the only class
   that needs a warning built for it. That is `_DIVERGENCES` below.

Why not a static analyser: sqlglot's own signals do not carry this
information. Of the four expressions Postgres rejects outright,
`exp.Anonymous` identifies one and `Generator.unsupported_messages`
identifies none — a warning built on either would be confidently wrong.

**`_DIVERGENCES` is a measured list, not an exhaustive one.** An empty
result means "nothing known here", never "verified equivalent". The UI is
built to match: it renders no affirmative all-clear state.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# The dialect every fragment is written in. Fragments are authored against
# DuckDB because that is the engine's own dialect and the one the docs and
# the Filter Basic tab generate.
SOURCE_DIALECT = "duckdb"


@dataclass(frozen=True)
class DialectNote:
    code: str
    message: str


# (dialect, unit) → what that engine actually computes, measured by
# transpiling every unit the recipe picker offers. Two engines drop the unit
# entirely and hand back days, which is a wrong number rather than a
# different convention. "*" applies to every unit except day.
_DATE_DIFF_MEASURED = {
    ("mysql", "*"): "ignores the unit and returns whole days",
    ("sqlite", "week"): "returns whole days, not weeks",
    ("sqlite", "quarter"): "returns whole days, not quarters",
    ("sqlite", "month"): "divides elapsed days by 30, so long months drift",
    ("sqlite", "year"): "divides elapsed days by 365, so leap years drift",
}

# Units where an engine that does respect the unit still disagrees with
# DuckDB: DuckDB counts boundaries crossed, AGE()-style arithmetic counts
# whole elapsed periods. Days and weeks are unambiguous.
_ANNIVERSARY_UNITS = ("year", "month", "quarter")


def _date_diff_note(node: exp.Expression, dialect: str) -> DialectNote | None:
    """What `date_diff(unit, …)` means on *dialect*, where that differs.

    Measured, dob=1990-12-31 as of 2026-08-25: DuckDB 36 years, Postgres 35.
    DuckDB counts year boundaries crossed; sqlglot renders Postgres as
    `EXTRACT(year FROM AGE(...))`, which only counts the year once the
    anniversary passes. SQLite and MySQL are worse — see the table above.
    """
    unit = node.args.get("unit")
    name = (unit.name if unit is not None else "").strip("\'\"").lower()
    if not name:
        return None
    detail = _DATE_DIFF_MEASURED.get((dialect, name))
    if detail is None and name != "day":
        detail = _DATE_DIFF_MEASURED.get((dialect, "*"))
    if detail is None:
        if name not in _ANNIVERSARY_UNITS:
            return None
        detail = (
            f"counts calendar {name} boundaries on duckdb but whole elapsed "
            f"{name}s"
        )
    return DialectNote(
        code="date_diff_unit_semantics",
        message=(
            f"date_diff('{name}', …) {detail} on {dialect} — the same two "
            "dates can produce a different number. For an age or eligibility "
            "check, decide which one you mean."
        ),
    )


def _try_cast_note(node: exp.Expression, dialect: str) -> DialectNote | None:
    """`try_cast` degrades to a plain `CAST` outside DuckDB.

    Measured: 'oops' → NULL on DuckDB, and an error that fails the whole
    run on Postgres. The contract inverts, so the note is worth showing
    even though the failure is loud.
    """
    return DialectNote(
        code="try_cast_becomes_cast",
        message=(
            f"try_cast returns NULL for a value that will not convert, but "
            f"on {dialect} it compiles to a plain CAST, which raises and "
            "fails the run instead. Guard the input, or filter it first."
        ),
    )


# sqlglot node type → note builder. Matching on the parsed tree, never on a
# substring: a column called `my_date_diff_col` is not a call to date_diff.
_DIVERGENCES = {
    exp.DateDiff: _date_diff_note,
    exp.TryCast: _try_cast_note,
}


def _parse(expr: str) -> exp.Expression | None:
    """Parse a fragment, or None. Half-typed input is the normal case here —
    this runs on every keystroke, so a parse failure is not an error."""
    if not expr or not expr.strip():
        return None
    try:
        return sqlglot.parse_one(expr, read=SOURCE_DIALECT)
    except Exception:
        return None


def notes_for(expr: str, dialect: str) -> list[DialectNote]:
    """Known meaning-changes for *expr* when executed on *dialect*.

    Empty for duckdb: the fragment is already written in that dialect, so
    there is nothing to transpile and nothing to diverge from.
    """
    if dialect == SOURCE_DIALECT:
        return []
    tree = _parse(expr)
    if tree is None:
        return []
    notes: list[DialectNote] = []
    seen: set[str] = set()
    for node_type, build in _DIVERGENCES.items():
        for node in tree.find_all(node_type):
            note = build(node, dialect)
            if note is not None and note.code not in seen:
                seen.add(note.code)
                notes.append(note)
    return notes


def transpile_fragment(expr: str, dialect: str) -> str | None:
    """What *dialect* actually receives, or None when there is nothing to say.

    None covers three cases the editor should stay quiet about: the target
    is DuckDB, the fragment does not parse yet, and the output is what the
    user already typed.
    """
    if dialect == SOURCE_DIALECT or not expr or not expr.strip():
        return None
    try:
        out = sqlglot.transpile(expr, read=SOURCE_DIALECT, write=dialect)[0]
    except Exception:
        return None
    if out.strip().lower() == expr.strip().lower():
        return None
    return out


# Ops whose `expr` is a user-authored raw-SQL fragment. `map` only counts
# in its expression/calculation modes — a lookup map has no SQL at all.
def raw_sql_fragment(step: dict) -> str | None:
    """The raw-SQL fragment a step carries, or None if it has none.

    One list, so the readback covers exactly the surfaces that escape to
    SQL. A step added to the editors without being added here silently
    loses its feedback, which is why this lives beside the notes rather
    than in the route.
    """
    op = step.get("op")
    if op in ("filter", "check"):
        expr = step.get("expr")
    elif op == "map" and step.get("mode") in ("expression", "calculation"):
        expr = step.get("expr")
    else:
        return None
    return expr if isinstance(expr, str) and expr.strip() else None


def execution_dialect_of(table) -> str:
    """The dialect the table's own backend speaks.

    ibis backend `.name` ("duckdb", "postgres", "sqlite", …) is already a
    valid sqlglot dialect name, so it doubles as both. Falls back to
    duckdb — a wrong-but-quiet readback beats an exception in a callback
    that exists to render feedback.
    """
    try:
        return table._find_backend().name
    except Exception:
        return SOURCE_DIALECT
