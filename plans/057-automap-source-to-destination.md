# 057 — Automap: source schema → destination schema

Branch: `feature/automap`

## Problem

A DB→DB pipeline is mapped one column at a time. You read the source schema
in `SourcesPanel`, then hand-type each `rename` row and each `select` field
— while **guessing the destination's column names**, because the builder has
never known them. `Destination.config` for a `postgres` / `sql_database`
target carries `{schema, table, write_disposition}` and nothing else, and
there was no destination-schema endpoint at all.

A typo lands as a `rename` to a column the target doesn't have, and the
first sign of it is a failed write at trigger time.

## Architecture change

Three additions, no new step op, no migration, no new dependency.

1. **Destinations become introspectable.** `GET /api/destinations/{id}/schema`
   opens the destination's connection with the existing
   `_open_ibis_backend` (`dte/engine/backend_registry.py`) and returns the
   target table's columns through `schema.py`'s `InferSchemaResponse` /
   `_walk` — the same field-tree shape sources already return, so the
   frontend has one schema type, not two. File targets 422: their shape is
   whatever the pipeline writes, so there is nothing to read.

2. **`dte/automap.py`** — a pure matcher over two field lists.
   - **exact** on the normalised name (`customer_id` == `CustomerID`).
   - **fuzzy** via `difflib.SequenceMatcher`, cutoff `0.8`, greedy
     best-first so the strongest pair claims a column before a weaker one.
     stdlib: deterministic, free, and the pass CI can run.
   - **llm** over the leftovers only, one Claude call, gated on
     `ANTHROPIC_API_KEY`. Semantic renames (`dob` → `birth_date`) are the
     only reason it exists. Its failure is an `llm_error` string, never a
     failed request — the heuristic answer is still worth showing. Names
     not in the input lists are discarded, and it cannot take a column the
     heuristic already claimed.
   - A **type-family mismatch never rejects a match**: it attaches a
     warning (`int64 → string`) and caps confidence at `0.5`. Rejecting
     would hide the exact-name pairs people most want to look at, and
     capping is what keeps such a row from being pre-ticked.

3. **`POST /api/schema/automap`** takes *field lists, not ids* — the builder
   already holds the source fields in `SchemaProvider` and fetches the dest
   fields from (1). The route stays a pure call into the matcher with no
   store access and no source loading, which is why it is tested without
   mocking any I/O.

### Frontend

`components/builder/AutoMap.tsx` — one `AutoMapButton` rendering both the
button and its portaled dialog. It is in the **Ordered steps** panel head on
both step surfaces: `steps/StepsPanel.tsx` (new-pipeline builder) and
`pipeline/steps-column.tsx` (pipeline detail). Both already own `steps` +
`onChange`; each gained an `outputId` prop.

- Source fields come from `fieldsAtStep(steps.length)`, not `allFields` —
  the generated steps append at the end, so the columns that exist *there*
  are the ones to map, after any earlier rename.
- The proposal fires from the click that opens the dialog, not a mount
  effect. A paid model call should not be reachable by a render.
- **Nothing is applied on arrival.** Every row is a checkbox; only
  `confidence >= 0.9` starts ticked (so a type-mismatch row never does), and
  a guessed source is editable in place via `FieldPicker`. Accepting writes
  **one `select` step**, aliased (`{field: source, alias: dest}`) — ordinary
  and inspectable afterwards.
- **No `rename` step.** `OutputField.alias` already renames, so a rename
  alongside the select was pure redundancy — and `_apply_rename` validates
  against `table.columns`, so it raises on the dotted struct paths
  (`order.amount`) that `_apply_output_fields` resolves via
  `_resolve_field`. Emitting one select is both smaller and strictly more
  capable.

## Deliberately not built

- No `automap` step op and no persisted mapping — the output is one normal
  step you can read and edit. Schema drift does not auto-follow.
- No many-to-one or expression mappings (`first || ' ' || last`). That is a
  `map` step and a different feature.
- No caching. The heuristic is microseconds; the model pass only ever sees
  leftovers.

## Files

| File | Change |
|---|---|
| `backend/dte/automap.py` | new — the matcher |
| `backend/dte/api/routes/destinations.py` | + `GET /{id}/schema` |
| `backend/dte/api/routes/schema.py` | + `POST /schema/automap` |
| `backend/tests/unit/test_automap.py` | new |
| `backend/tests/unit/test_api_automap.py` | new |
| `frontend/src/lib/api.ts` | + `getDestinationSchema`, `automapFields` |
| `frontend/src/components/builder/AutoMap.tsx` | new |
| `frontend/src/components/builder/steps/StepsPanel.tsx` | + button, `outputId` prop |
| `frontend/src/components/builder/BuilderForm.tsx` | passes `outputId` |
| `frontend/src/components/pipeline/steps-column.tsx` | + button, `outputId` prop |
| `frontend/src/components/pipeline/canvas.tsx` | passes `outputId` |

## Verification

```bash
cd backend && uv run pytest tests/unit -q       # 6 pre-existing trino-extra failures only
cd frontend && pnpm exec tsc --noEmit && pnpm build
```

End-to-end, **run** against the dev Postgres (`raw.orders` →
`analytics.orders_clean`): exact (`customer_id`→`CustomerID`), fuzzy
(`ship_date`→`shipping_date`), type-warned (`decimal(10,2)`→`string`, capped
at 50% and not pre-ticked), llm (`dob`→`birth_date`) and unmatched
(`tax_region`) all appeared in one dialog. Accepting wrote the select, the
live preview re-rendered with destination-named columns, Save persisted it,
and a trigger completed writing 2 rows.

Two things that run found, both worth knowing:

- **Fixed here.** `propose` was memoized on `[outputId]` and closed over a
  `sourceFields` captured before schema inference returned, so the first
  open showed every row unmapped against a destination whose columns had
  loaded fine. It is a plain function now — it is only ever called from the
  click handler, so there was never a reason to memoize it.
- **Not fixed, pre-existing.** The Postgres writer goes through dlt, which
  normalises identifiers to snake_case: `shipping_date` and `birth_date`
  landed, `CustomerID` did not — dlt created a `customer_id` column beside
  it and left `CustomerID` null. So automap will propose a mapping to any
  non-snake_case destination column that the writer then cannot target.
  Fixing it means setting dlt's naming convention in
  `engine/writers/postgres.py`, which touches every existing postgres
  destination.
