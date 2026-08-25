# Plan 061 — `case` step (if / else)

## Context

Conditional column derivation is only expressible today by typing raw SQL into a
`map` / `expression` step: `CASE WHEN "amount" >= 1000 THEN 'gold' ELSE 'bronze' END`.
The compiler already handles it (`_apply_expression` → `engine.apply_expression_sql`),
so the engine gap is zero — the gap is that a conditional cannot be *built*. Every
other comparison surface in the product (Filter Basic) gives a field picker, an
operator dropdown and injection-safe quoting; conditionals give a blank textarea.

Outcome: a first-class **Case** step in the Add-step menu whose branches are built
with the same rule UI as Filter, and which round-trips on reopen because the step
dict *is* the editor state — no SQL parser.

## Wire shape

```json
{ "op": "case",
  "output_field": "tier",
  "branches": [
    {"when": "\"amount\" >= 1000", "then": "'gold'"},
    {"when": "\"amount\" >= 100",  "then": "'silver'"}
  ],
  "otherwise": "'bronze'" }
```

`when` / `then` / `otherwise` are SQL fragments — the same trust model as
`FilterStep.expr` and `ExpressionMapStep.expr`, and the UI never concatenates
user input without `quoteIdent` / `safeLiteral`.

## Backend — `backend/dte/`

1. **`models/pipeline.py`** (next to `ExpressionMapStep`, ~line 707):

   ```python
   class CaseBranch(BaseModel):
       model_config = {"extra": "forbid"}
       when: str   # SQL boolean expression
       then: str   # SQL literal or expression

   class CaseStep(BaseModel):
       op: Literal["case"]
       output_field: str
       branches: list[CaseBranch] = Field(min_length=1)
       otherwise: str | None = None
   ```
   Reuse the `_non_empty` validator pattern from `FilterStep` for `when`/`then`
   and `output_field` — an empty branch renders as `WHEN  THEN` and fails as a
   DuckDB parse error naming nothing useful.

   Register in `_STEP_MODELS` (~line 1144): `("case", None): CaseStep`.
   No change to `_validate_steps` — `case` is legal in every pipeline type.

2. **`compiler/ibis_compiler.py`** — dispatch in `_dispatch_single_table_step`
   (~line 244), and compile by *delegating to the existing expression path*, not
   by adding a second raw-SQL seam:

   ```python
   elif op == "case":
       return _apply_case(table, CaseStep(**step), engine=engine)

   def _apply_case(table, step, engine=None):
       whens = " ".join(f"WHEN {b.when} THEN {b.then}" for b in step.branches)
       otherwise = f" ELSE {step.otherwise}" if step.otherwise is not None else ""
       return _apply_expression(
           table,
           ExpressionMapStep(op="map", mode="expression",
                             output_field=step.output_field,
                             expr=f"CASE {whens}{otherwise} END"),
           engine=engine,
       )
   ```
   This inherits the `BaseEngine` seam for free (Trino raises
   `TrinoRawSqlNotSupported` exactly as it does for filter/map today).

3. **`compiler/interpolate.py`** — `_STEP_STRING_FIELDS` is a flat
   op → top-level-field map, so `{{params.x}}` inside `branches[]` would silently
   survive into the SQL and fail at parse time. Add `"case": ("otherwise",)` and,
   in the loop at ~line 265, interpolate `when`/`then` on each branch dict of a
   `case` step (the step is already `deepcopy`d there).

## Frontend — `frontend/src/components/builder/steps/`

4. **Extract the rule builder** from `FilterEditor` in `editors.tsx`
   (lines ~676–807: the rule rows, `+ Add condition`, `Generated SQL` preview)
   into a `ConditionRules({ rules, onChange })` component in the same file.
   `FilterEditor` becomes its first consumer with no behaviour change; the case
   editor is the second. `quoteIdent` / `safeLiteral` / `rulesToSql` /
   `tryParseBasicSql` / `DateValueField` stay where they are and are shared.

5. **`CaseEditor`** — output-field input, then a list of branches. Each branch is
   a `<ConditionRules>` (emitting `when` via `rulesToSql`, parsing back via
   `tryParseBasicSql` on mount) plus a value input for `then` run through
   `safeLiteral`; a final "Otherwise" value input. Reorder/remove per branch,
   mirroring `StepsPanel`'s ↑/↓/× affordances. Dispatch from `StepEditor`
   (~line 2179).

6. **`types.ts`** — add `"case"` to `StepOp`, a `{ op: "case", label: "Case · if/else",
   category: "transform" }` entry in `STEP_OPS`, and
   `case "case": return { op, output_field: "", branches: [{ when: "", then: "" }],
   otherwise: null }` in `emptyStep` (one starter branch — `min_length=1` means a
   zero-branch step cannot be saved, and a step you can't save is a bad first
   impression, same reasoning as `structure`).

7. `pnpm gen:types` with the backend up on `:8001`.

## Verification

```bash
cd backend && uv run pytest tests/unit/test_compiler.py -k case      # TDD: write first
cd backend && uv run pytest tests/scenarios -m scenario -k case      # new tests/scenarios/steps/test_case.py
cd frontend && pnpm exec tsc --noEmit
```

- Unit tests (write before the compiler code): a two-branch case with `otherwise`
  produces the expected column; no `otherwise` → NULL for unmatched rows; an
  interpolated `{{params.threshold}}` inside a branch resolves.
- Scenario test over `orders.json`: add a `case` step tiering `amount`, assert
  the exact output row set — one file per op under `tests/scenarios/steps/`.
- Manual: `docker compose -p dte up -d`, add a Case step in the builder, hit
  Preview on the pipeline detail page, reopen the pipeline and confirm the
  branches repopulate.

## Skipped

- No `then`-as-expression toggle (`THEN other_column`) — value literals only.
  Add when someone asks; raw `map`/`expression` covers it meanwhile.
- No migration: `Pipeline.steps` is `list[dict]` JSONB, existing steps untouched.
- No nested/`case`-inside-`case` UI. YAGNI.


---

## Revision — portable compilation (after first review on a DB source)

The first cut compiled `case` to a `CASE WHEN` **string** and reused
`_apply_expression`. That inherits the raw-SQL escape hatch, and
`_require_duckdb_backend` refuses it on any natively-bound table — so the step
was unusable on exactly the pipelines plan 056 exists to serve. Caught by
running it against a real `sql_database` source.

Changed:

- `CaseCondition {field, op, value, join}` replaces the SQL-string `when`.
  `_apply_case` emits `ibis.cases` (as `_apply_lookup` already did), so the
  step runs on Postgres/MySQL/DuckDB alike. `_case_predicate` reproduces SQL's
  AND-over-OR precedence.
- `then`/`otherwise` are plain scalars, not SQL literals — no quoting surface
  at all, and the editor drops `rulesToSql`/`tryParseBasicSql` entirely.

## Revision 2 — the guard was the bug

Revision 1 added a `date_diff` step because "there is no portable way to
derive age". That was wrong, and adding an op per SQL function is the wrong
shape regardless: `map`/`expression` already computes columns. The real
defect was one level down.

`DuckDBEngine.apply_filter_sql` / `apply_expression_sql` built their SQL by
creating a **view inside the engine's own DuckDB connection**, which only
works for DuckDB-bound tables — hence `_require_duckdb_backend`, hence raw
SQL being refused on every `sql_database` source.

`table.alias(name).sql(fragment, dialect="duckdb")` has neither problem: it
rides on the table's own backend, sqlglot transpiles the fragment to that
backend's dialect, and nothing is written to the user's database. The guard
and `date_diff` are both deleted; `map`/`expression` and Advanced filter now
work on DB sources, which is what they were always supposed to do.

`case` stays structured — not because raw SQL is unavailable, but because
the rule list is the shape the builder already produces and it round-trips
without a parser.
