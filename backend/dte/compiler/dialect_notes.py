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


def _date_diff_note(node: exp.Expression, dialect: str) -> DialectNote | None:
    """`date_diff('year', ...)`: calendar boundaries vs whole elapsed years.

    Measured, dob=1990-12-31 as of 2026-08-25: DuckDB 36, Postgres 35.
    DuckDB counts year boundaries crossed; sqlglot renders Postgres as
    `EXTRACT(year FROM AGE(...))`, which only counts the year once the
    anniversary passes. Days and weeks are unambiguous, so only year and
    month are flagged.
    """
    unit = node.args.get("unit")
    name = (unit.name if unit is not None else "").strip("'\"").lower()
    if name not in ("year", "month"):
        return None
    return DialectNote(
        code="date_diff_calendar_vs_anniversary",
        message=(
            f"date_diff('{name}', …) counts calendar {name} boundaries on "
            f"duckdb but whole elapsed {name}s on {dialect} — the same row "
            "can produce a different number. For an age or eligibility "
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
