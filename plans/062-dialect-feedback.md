# Plan 062 — Dialect feedback in the expression editors

*(Plan 061, the `case` step + portable raw SQL, is already committed on
`feature/case-step` / PR #1. This is the follow-on and shares that branch.)*

## Context

Raw SQL now runs on every backend: `table.alias(name).sql(fragment,
dialect="duckdb")` transpiles a DuckDB-dialect fragment through sqlglot to
whatever the source's own backend speaks. Reach is solved. **Meaning is not**,
and nothing in the UI says so.

Measured against live Postgres — 55 DuckDB expressions transpiled and executed:

- **51 run correctly.** Rewritten as needed (`strftime`→`TO_CHAR`,
  `regexp_matches`→`~`, `last_day`→`DATE_TRUNC + INTERVAL`, `ifnull`→`COALESCE`).
- **4 fail outright**: `datepart`, `contains`, `string_split`, `len(array)`.
  Loud, and the database's own message is the best possible copy.
- **2 run and silently mean something else** — the dangerous class:

  ```
  date_diff('year', dob, current_date)    dob=1990-12-31, today=2026-08-25
      DuckDB   → 36   (calendar-year boundaries)
      Postgres → 35   (AGE() is anniversary-aware)
  ```

  and `try_cast` → plain `CAST`: NULL on DuckDB, **raises** on Postgres.

Two further problems this surfaces:

- `step_sqls` / `final_sql` are rendered with `getattr(engine, "dialect",
  "duckdb")`, which is *always* `"duckdb"` for `DuckDBEngine`. **The SQL panel
  shows DuckDB SQL for a Postgres pipeline** — it displays something that
  never runs.
- A compile error arrives as one blob at the bottom of the preview pane with
  no attribution, so a bad expression in step 2 reads as "the pipeline is
  broken".

Outcome: every raw-SQL input renders what the target database will actually
receive, as you type — `frontend/DESIGN.md` **"Feedback beats validation"**,
the rule the Filter Basic tab's *Generated SQL* readback already follows.

## Why not a static analyser

sqlglot's own signals are not usable for this. Measured on the four
expressions that genuinely fail on Postgres:

| signal | caught |
|---|---|
| `exp.Anonymous` nodes | 1 of 4 (`datepart` only) |
| `Generator.unsupported_messages` | 0 of 4 |

A warning built on those would be confidently wrong. The reliable signal is
compilation against the real backend, which the builder **already performs on
every edit**.

## The seam: extend what already runs

`POST /api/pipelines/step-schemas` already compiles step-by-step via
`on_step_schema`, tolerates a mid-pipeline failure, and returns partial
results. `AutoStepSchemas` (`components/pipeline/schema-sync.tsx`) already
debounce-fetches it on every edit in **both** hosts, and pushes results into
`SchemaProvider`, which every editor reads through `useStepFields()`.

Extend that one payload. No new endpoint, no new fetch, no new debounce, no
new provider mount.

## Backend — `backend/dte/`

1. **`compiler/ibis_compiler.py`** — the `on_step_sql` callback renders with
   `getattr(engine, "dialect", "duckdb")`. Use the table's *own* backend
   instead: `registry[current_key]._find_backend().name` (ibis backend `.name`
   is already a valid sqlglot dialect string). Same fix at both
   `final_sql` sites in `api/routes/pipelines.py`.

2. **`compiler/dialect_notes.py`** (new, ~40 lines) — the measured
   divergence table plus `notes_for(expr, dialect) -> list[Note]`. Keyed by
   function name, matched on the parsed sqlglot tree, not by substring.
   Ships with the two cases above and a docstring stating plainly that it is
   a **measured list, not an exhaustive one** — the next person must not read
   an empty result as a guarantee.

3. **`api/routes/pipelines.py`** — `step-schemas` gains, alongside
   `step_schemas`:
   - `dialect: str` — the execution dialect.
   - `step_expr_sql: {index: str}` — **the fragment alone**, transpiled
     (`sqlglot.transpile(expr, read="duckdb", write=dialect)`), for
     `filter` / `map`(expression|calculation) / `check` steps. The full step
     SQL is a `WITH … SELECT *` blob; the fragment is what the user typed and
     is what belongs beside the input.
   - `error_step: int | None` — index of the step being applied when compile
     failed (track the cursor already threaded through `on_step_schema`).
   - `warnings: [{step, code, message}]` from `dialect_notes`.

   All four are omitted/empty for a DuckDB pipeline, so nothing changes for
   the common case.

## Frontend — `frontend/src/components/`

4. **`builder/schema-context.tsx`** — carry the new fields next to
   `perStepSchemas` (identical shape and lifecycle), and export a
   `useStepFeedback()` hook returning `{dialect, exprSql, error, warnings}`
   for the current index. `StepIndexContext` already exists and already wraps
   every editor in both hosts — export a `useStepIndex()` beside
   `useStepFields()` rather than threading a prop.

5. **`pipeline/schema-sync.tsx`** — `AutoStepSchemas` stores the new fields
   from the same response it already receives. No second request.

6. **`builder/steps/editors.tsx`** — one `<DialectReadback />` component,
   rendered under the textarea in **all three** raw-SQL surfaces:
   `MapExpressionEditor`, `FilterEditor` (Advanced tab), `CheckEditor`
   (Advanced tab). Mirrors the existing *Generated SQL* block in
   `ConditionRules` so Basic and Advanced read as one family.

   ```
   AS POSTGRES
   CAST(EXTRACT(year FROM AGE(CURRENT_DATE, dob)) AS BIGINT)

   ⚠ date_diff('year', …) counts calendar years on DuckDB and whole years
     on Postgres — same data, different number.
   ```

   - Renders **only when the transpiled fragment differs from what was
     typed**, or a warning/error applies. A DuckDB pipeline stays silent.
   - Errors attach to their own step when `error_step` matches this index —
     the database's message, verbatim, next to the expression that caused it.
   - Reuse `Pill` (`warn` gold / `failed` red) — both tones already exist.
   - **No affirmative green "validated" state.** The divergence list is
     measured, not exhaustive; a checkmark would promise a guarantee this
     cannot make.

## Verification

```bash
cd backend && uv run pytest tests/unit/test_compiler.py -k dialect
cd backend && uv run pytest tests/scenarios -m scenario -k "dry_run or step_schemas"
cd frontend && pnpm exec tsc --noEmit && pnpm test
```

- Unit (write first): `notes_for("date_diff('year', a, b)", "postgres")`
  returns one note and `("upper(s)", "postgres")` returns none; step SQL for a
  SQLite-bound table renders as SQLite, not DuckDB — the `sqlite_people`
  fixture added in plan 061 is already there for exactly this.
- Scenario: `step-schemas` on a pipeline over a `sql_database` source returns
  `dialect: "postgres"` and a transpiled `step_expr_sql`.
- Manual, and the reason this plan exists — the stack is already up from this
  worktree with a Postgres-backed pipeline at
  `/pipelines/7b528d64-f884-4d49-b4dd-bfecef8fb746`: put
  `date_diff('year', birth_date, {{today}}::date)` in step 2 and confirm the
  readback shows the `AGE(...)` form plus the divergence warning; then type
  `contains(s,'A')` and confirm Postgres's own error appears on **that step**,
  not only in the preview pane.

## Skipped

- No new step op, no new endpoint, no new fetch — the user asked for a visual
  interface on the existing expression steps, and the payload that feeds it
  already arrives on every keystroke.
- No JS-side transpiler. sqlglot is Python-only; a second implementation
  would drift from the one that actually compiles the pipeline.
- Not fixing the 4 hard-failure expressions (`contains` → `LIKE`, etc.) with
  auto-rewrites. Silently rewriting what the user typed is forbidden by
  DESIGN.md, and naming the problem is the ask.
