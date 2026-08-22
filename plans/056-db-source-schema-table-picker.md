# Plan 056 — DB sources are database-scoped; tables are picked in the pipeline

> **Clean break.** Existing pipelines are dropped, not migrated. No
> back-compat shim, no dual-shape reader, no coercion validator. Migration
> `037` truncates `pipelines` and `pipeline_revisions`.

## Problem

A `sql_database` Source is bound to exactly one physical table:
`SqlDatabaseSourceConfig.table` is required (`dte/models/pipeline.py:345-350`)
and `_load_sql_database` reads `config["table"]` to return a single ibis
table (`dte/sources/loader.py:229-250`).

Joining `orders`, `customers`, `products` out of one Postgres database
therefore needs **three Source rows**, each hand-typing a schema and table
name into a bare text `Input` (`SqlSourceEditor.tsx`). Nothing lists the
available schemas or tables — `probe_connection` only runs `SELECT 1`
(`dte/sources/connection_test.py:33-48`), and `POST /api/schema/infer`
infers the *columns* of an already-chosen table. A typo'd table name is
discovered when a run fails.

A database connection legitimately has many tables a pipeline wants. The
table binding belongs where the pipeline decides what it joins.

## Architecture

### The central decision: the ref names itself

```
Connection (creds)
    ↑
Source (connection_id + config["schema"])     ← a database/schema. No table.
    ↑
Pipeline.sources: list[SourceTableRef]        ← {source_id, table, alias}
    ↑ JoinStep.left/right reference the alias
```

```python
class SourceTableRef(BaseModel):
    source_id: str
    table: str | None = None   # required for sql_database, forbidden otherwise
    alias: str                 # the compiler registry key. Required, unique.
```

**`alias` is the registry key, and it is explicit.** Not
`f"{source_id}::{table}"`. A composite string key was the first design and
it is wrong four ways, all of which `alias` fixes for free:

- **Ambiguity.** A quoted Postgres identifier may contain `::`, so the key
  cannot be reliably split back apart.
- **Self-joins become impossible.** Today two Source rows on the same table
  give two registry keys. Collapsing to one source + one table gives one
  key, and `orders o1 JOIN orders o2` can no longer be expressed. A
  user-chosen alias restores it.
- **Duplicate refs silently collapse.** Two refs to the same pair produce
  one dict entry; the second overwrites the first. That is precisely the
  silent-collapse failure this plan exists to remove. Alias uniqueness is
  checked at save → 422.
- **Non-DB sources need no sentinel.** A filesystem source has no table;
  its ref is `{source_id, table: null, alias: "invoices"}`. The composite
  scheme forced a `srcid::srcid` sentinel that then leaked into the join
  operand labels users read.

`alias` is **required on the wire**, never defaulted server-side. Defaulting
it would need the Source row's own view name, which means a store lookup
inside a Pydantic validator — sync, no DB access, not implementable. The
builder already holds the source list via SWR, so it fills the alias in
when the user picks a table (`orders`, then `orders_2` on collision). The
backend only validates.

Validation lives in the route layer where the store is reachable
(`_validate_pipeline_refs`), not in a model validator:

- every `source_id` exists (as today);
- `alias` is unique within the pipeline, non-empty, `^[A-Za-z_][A-Za-z0-9_]*$`;
- `table` is **required** when the resolved source is `sql_database`, and
  **must be absent** for every other kind;
- every `JoinStep.left`/`.right` resolves to a declared alias or an earlier
  step's `output_id` — today an unknown ref raises a bare `KeyError` deep in
  the compiler (`ibis_compiler.py:172-176`), which is a 500. Checking it at
  save makes it a 422 naming the bad operand.

### `load_source` takes the table as a parameter

`load_source(source, registry, connection, credentials, table=None)`. The
`table` argument is threaded to `_load_sql_database`, which uses it instead
of `config["table"]`. Every other loader ignores it.

The alternative — mutating `source.config["table"]` at the call site for the
duration of the load — is rejected: `Source` instances are SQLAlchemy
instrumented and cached per request, so mutation is both a shared-object
hazard and invisible at the call site.

`Source.table` (the top-level column, DB column `table_name`) is
**untouched**. It is the DuckDB **view name** for filesystem / mongodb /
rest_api / documents sources (`loader.py:152,186,275,287,410`), not a
physical table reference. It stays `NOT NULL`. Only `sql_database`'s
`config["table"]` is removed — that kind goes to a native ibis backend
(`registry.for_connection`, `backend_registry.py:55-69`) and never creates
a view, so its `Source.table` is already just a label.

### Introspection endpoints

DB connections open a **native, connection-id-cached ibis backend**
(`_open_ibis_backend`, `backend_registry.py:75`) — not a DuckDB `ATTACH`.
So listing is a direct backend call on an already-warm connection:

- `GET /api/connections/{id}/schemas` → `{schemas: [...]}` via
  `backend.list_databases()`. Gated `connection:read`. 422 when the
  connection type has no native backend (`NotImplementedError` from
  `_open_ibis_backend`).
- `GET /api/sources/{id}/tables` → `{tables: [...]}` via
  `backend.list_tables(database=config.get("schema"))`. Gated
  `source:read`. 422 for non-`sql_database` kinds.

Both permissions already exist (`dte/security/permissions.py:17,19`), so no
roles migration is required. Both are read-only, uncached — a stale list is
tolerable exactly as it is for `/api/schema/infer`.

### Schema inference has to carry a table

`POST /api/schema/infer` calls `load_source(source, ...)` on the request
body (`dte/api/routes/schema.py:43-64`). A table-less DB source cannot load,
so it 422s — and this endpoint feeds `SchemaProvider` → `allFields` → every
FieldPicker, Select, Filter and Rename editor. Without this the builder has
no field autocomplete for any DB pipeline.

- Request body gains an optional `table: str | None`, passed through to
  `load_source`.
- `GET /api/sources/{id}/schema` gains `?table=`.
- `SchemaProvider` (`components/builder/schema-context.tsx`) re-keys from
  `{[source_id]: fields}` to `{[alias]: fields}`. Alias is the right key:
  it is unique per pipeline and is what steps reference, so a two-table
  pipeline gets two distinct field sets instead of one overwriting the
  other. `allFields` stays a deduped union.
- `refresh`/`refreshById` and `AutoInferSchemas` take the ref, not the id.

## Task list

Branch: `feature/056-db-source-schema-table-picker`

1. **Models** — `SourceTableRef`; `Pipeline.sources: list[SourceTableRef]`;
   drop `table` from `SqlDatabaseSourceConfig` (keeps `extra="forbid"`).
   `dte/models/pipeline.py`.
2. **Migration `037`** (head is `036`, `036_pipeline_matrix.py`) —
   `DELETE FROM pipeline_revisions; DELETE FROM pipelines;` (runs reference
   revisions via `ON DELETE SET NULL`, so runs survive with a null
   `revision_id`); strip the `table` key from `config` on every
   `sql_database` row in `sources`. Under 100k rows by construction, so no
   `batched_update` needed — note why in the migration docstring.
3. **Introspection** — `list_schemas` / `list_tables` helpers in
   `dte/sources/loader.py`; routes in `dte/api/routes/connections.py` and
   `dte/api/routes/sources.py`.
4. **`load_source` table parameter** — signature change + `_load_sql_database`.
   `dte/sources/loader.py`.
5. **Ref resolution** — the six sites that today do `s_store.get(sid)` on a
   bare string: `_validate_pipeline_refs` (`pipelines.py:176`), engine-compat
   (`:216`), local_fs check (`:289`), `_resolve` (`:695`), `_resolve_sources`
   (`:726`), and the metrics label in `dte/worker/tasks.py:98`. All read
   `ref.source_id`. Alias/table/join-operand validation added to
   `_validate_pipeline_refs`.
6. **Compiler** — registry keyed by `ref.alias`; `current_key` seeds from
   `pipeline.sources[0].alias` (`ibis_compiler.py:159`); the `tables` dict at
   each build site passes `ref.table` into `load_source`. Compiler tests
   first, per repo TDD convention.
7. **Delete guard** — `sources.py:114,131` use `sid in (p.sources or [])`.
   String membership against objects is always `False`, so an in-use source
   would delete cleanly and every pipeline referencing it 422s at next run.
   This fails *open*; rewrite as
   `any(r.source_id == sid for r in p.sources)`.
8. **Schema inference** — `table` on `POST /api/schema/infer` and
   `GET /api/sources/{id}/schema`. `dte/api/routes/schema.py`,
   `dte/api/routes/sources.py`.
9. **Frontend — validation.** `src/lib/validation.ts:61-70` has two guards
   that fail open on objects: `sources.every((s) => Boolean(s))` (the empty
   -slot check — `{}` is truthy, so an unpicked slot passes) and
   `new Set(sources).size === sources.length` (the duplicate check — object
   identity never collides, so dedupe silently dies). Rewrite both against
   `alias`, and add an alias-format rule.
10. **Frontend — source editor.** `SqlSourceEditor.tsx`: drop the `table`
    input; turn `schema` into a dropdown fed by
    `GET /api/connections/{id}/schemas`.
11. **Frontend — pipeline surfaces.** `SourcesPanel.tsx` slot model becomes
    `{source_id, table, alias}` with a table dropdown fed by
    `GET /api/sources/{id}/tables` and an editable alias; join operand
    pickers in `steps/editors.tsx` list aliases. Also touched, all of which
    map over `pipeline.sources` as bare ids today:
    `components/pipeline/canvas.tsx:237,241,384` (SourcesCard,
    AutoInferSchemas), `pipeline/schema-sync.tsx:37`,
    `pipeline-preview.tsx:113`, `pipelines/[id]/page.tsx:26`,
    `pipelines/[id]/revisions/[revId]/page.tsx:42`,
    `lib/eval-eligibility.ts:33` (`.includes(sourceId)` — same fail-open
    membership break as task 7), `builder/BuilderForm.tsx:70,173,292`.
12. **`pnpm gen:types`** (backend up on `:8001`).
13. **Scenario test** — `tests/scenarios/steps/test_join_single_source_multi_table.py`:
    one Postgres connection, **one** `sql_database` Source, a pipeline
    picking 3 tables from it, joining and aggregating. This is the
    acceptance test for the whole plan. It cannot be written as a red test
    against `main` — a table-less source is unconstructable there — so it
    lands with tasks 1-6.
14. **Docs** — CLAUDE.md: the "First-class sources and destinations",
    "Field references", and API surface sections all describe
    `sources: list[str]`.

## Files changed

**Backend**
- `dte/models/pipeline.py` — `SourceTableRef`, `Pipeline.sources`,
  `SqlDatabaseSourceConfig`.
- `alembic/versions/037_source_table_refs.py` — new.
- `dte/sources/loader.py` — `table` param, `list_schemas`, `list_tables`.
- `dte/api/routes/pipelines.py` — ref resolution ×5, alias/operand validation.
- `dte/api/routes/sources.py` — `/tables`, `?table=` on `/schema`, delete guard.
- `dte/api/routes/connections.py` — `/schemas`.
- `dte/api/routes/schema.py` — `table` on infer.
- `dte/compiler/ibis_compiler.py` — alias-keyed registry.
- `dte/worker/tasks.py` — metrics label.
- `tests/unit/test_compiler.py`, `tests/fakes.py`,
  `tests/scenarios/steps/test_join_single_source_multi_table.py`.

**Frontend**
- `components/builder/sources/SqlSourceEditor.tsx`, `SourcesPanel.tsx`
- `components/builder/steps/editors.tsx`, `schema-context.tsx`,
  `BuilderForm.tsx`
- `components/pipeline/canvas.tsx`, `schema-sync.tsx`,
  `components/pipeline-preview.tsx`
- `app/(app)/pipelines/[id]/page.tsx`, `.../revisions/[revId]/page.tsx`
- `lib/validation.ts`, `lib/eval-eligibility.ts`, `lib/api.ts`,
  `lib/api-types.ts` (regenerated)

**Docs** — `CLAUDE.md`

## Scope

`sql_database` only. `mongodb` / `rest_api` stay one source = one
collection/resource — dlt-backed, no schema to browse.
`filesystem` / `s3` / `gcs` / `azure` are unchanged in behaviour;
`file_glob` already lets one source match many files as one table. They
still move to the new ref shape (`table: null`), because
`Pipeline.sources` is one list for all kinds.

## Sharp edges

- **An alias is not a table name.** Two aliases may point at the same
  table (self-join). Anything that reverse-maps a registry key to a source
  must go through the ref, never parse the alias.
- **`list_tables` opens a real connection.** The backend is cached per
  `connection.id`, so the builder polling table lists is cheap after the
  first call — but the first call on a cold or unreachable connection
  blocks for the driver's connect timeout. The endpoint should surface that
  as a 422 with the driver's message, the way `probe_connection` does,
  rather than hanging the picker.
- **Dropping every pipeline is the migration.** It is irreversible and
  `runs` rows outlive their pipeline (`revision_id` nulls out), leaving run
  history pointing at pipeline ids that no longer resolve. Acceptable
  because this is pre-GA and explicitly sanctioned, but the run-detail page
  should tolerate a missing pipeline rather than 500.
