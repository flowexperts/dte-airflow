# Plan 063 — A UI for the common map expressions

## Problem

The expression box takes a raw DuckDB fragment. That is the right storage
format and the wrong first contact: knowing you want "whole months between
two dates" does not tell you it is spelled `date_diff('month', a, b)`, and
nothing in the builder does. Plan 062 made the box *honest* (it now shows
what the target database receives); it did not make it *findable*.

Not a new step — the ask was explicitly for better UI on what exists.

## Shape

A collapsed `+ build one` control under the expression textarea opens a
picker: choose a labelled shape ("Age / whole years between", "Percentage of
another field"), fill typed slots, watch the fragment build live, insert it.
It generates text into the existing `expr` and gets out of the way.

**One direction only.** No parse-back, no Basic/Advanced mode. The Filter tab
round-trips because rules are its primary representation; here the fragment
is the artifact, and a mode that had to re-parse arbitrary SQL would either
lie about what it captured or refuse to open. Insert, then edit by hand.

## What earns a slot in the list

1. **It transpiles.** Plan 062 measured 55 expressions against live Postgres.
   `datepart`, `contains`, `string_split`, `len(array)` and `try_cast` are
   excluded — a recipe is a recommendation, and those are measured to fail or
   invert meaning elsewhere. A unit test asserts none of them can appear.
2. **The name is the barrier.** `upper(x)` qualifies because "uppercase" is
   findable and `upper` is not. `a + b` does not.

`date_diff` is the one knowingly-divergent recipe kept: it is what people
come here for, and the dialect readback under the box names the divergence.

## Files

- `frontend/src/lib/sql-literal.ts` (new) — `quoteIdent` / `quoteString` /
  `safeLiteral` lifted out of `editors.tsx`, now that a second surface
  composes SQL from user input. No behaviour change.
- `frontend/src/lib/expression-recipes.ts` (new) — the recipe table and
  `buildRecipe`. Pure, so the SQL is unit-testable without a DOM.
- `frontend/src/components/builder/steps/editors.tsx` — `ExpressionRecipes`
  + `RecipeSlot`, rendered in `MapExpressionEditor` only.
- `backend/dte/compiler/dialect_notes.py` — see below.

## Fallout: date_diff is worse than 062 measured

062 measured `date_diff` for `year`. The picker offers every unit, so every
unit was measured, and two engines are wrong rather than merely different:

| engine | what `date_diff(unit, …)` actually returns |
|---|---|
| MySQL | **whole days, whatever unit you asked for** |
| SQLite | days for week/quarter; days÷30 for month; days÷365 for year |
| Postgres | anniversary-aware (`AGE`) for year/month/quarter |

`_date_diff_note` grows a measured `(dialect, unit)` table and now flags
quarter and week alongside year and month. Code renamed
`date_diff_calendar_vs_anniversary` → `date_diff_unit_semantics`, since
"calendar vs anniversary" describes only the Postgres row.

## Verification

```bash
cd frontend && pnpm exec tsc --noEmit && pnpm exec vitest run
cd backend  && uv run pytest tests/unit/test_dialect_notes.py
```

Pre-existing failures unrelated to this change: 6 in `test_engine_seam.py`
(missing `trino` extra) and 2 in `eval-eligibility.test.ts`.
