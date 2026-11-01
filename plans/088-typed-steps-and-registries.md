# 088 — Typed steps, one registry per extension point

## Problem

- **Steps are untyped.** `PipelineBase.steps: list[dict]`
  (`backend/dte/models/pipeline.py:1425`). They are validated through
  `_STEP_MODELS`, a `(op, mode)` dict (`pipeline.py:1192-1209`). OpenAPI
  therefore says nothing about steps, so the frontend writes them by hand in
  `components/builder/steps/types.ts` and `editors.tsx` (2.4k lines). Those
  hand-written types drift from the backend.
- **`lib/api.ts` is 1.4k hand-written lines** with about 80 types, while the
  generated `api-types.ts` (4.5k lines) is imported by only 2 files.
- **Adding a step type touches about 6 files** in two languages: the model plus
  `_STEP_MODELS`, the `if op ==` chain in `compiler/ibis_compiler.py:238-277`,
  `compiler/interpolate.py`'s `_STEP_STRING_FIELDS`, and `types.ts`,
  `editors.tsx` and `summary.tsx`.
- **Sources and writers dispatch through literals and if-chains.** That is
  `LOADERS` in `sources/loader.py:460`, `KINDS` in `airflow/connections.py:25`,
  `SOURCE_CONNECTION_COMPAT`, and the `isinstance` chain in
  `engine/writers/__init__.py:44`.
- `frontend/scripts/gen-api-types.sh` still points at a standalone uvicorn on
  :8000.

## Decision

- `steps: list[Step]`, where
  `Step = Annotated[Union[...], Field(discriminator="op")]`. `map`'s three
  modes become a nested discriminator on `mode`.
- **Strict on write, lenient on read stays.** Reads go through a `TypeAdapter`
  with a fallback that keeps unknown or legacy steps as `UnknownStep(raw: dict)`,
  so old revisions still load.
- **Each step class owns its compile function**, via a `compile(self, ctx, table)`
  method or a `@register("op")` decorator. Whichever is smaller wins; default
  to the method. The compiler's if-chain becomes `step.compile(...)`.
  `_STEP_STRING_FIELDS` becomes a class var.
- **Writers:** `target.write(...)` method, or a dict keyed by `type`.
  `LOADERS` is already a dict, so leave it.
- **Frontend:** step types come from generated `api-types.ts`.
  `lib/api.ts` keeps its fetch functions and re-exports generated types. Its
  hand-written types are deleted wherever a generated one exists.

- **`map`'s sub-discriminator** is a callable `Discriminator` returning a tag
  from `(op, mode)`: `map:lookup` / `map:expression` (which also takes
  `calculation`), `op` for everything else. A nested
  `Field(discriminator="mode")` validates, but FastAPI's OpenAPI model rejects
  the inline mapping it emits. The schema is a `oneOf` over every step class.
- **Writes store the dict as sent.** `PipelineBase.steps` validates each item
  against the union but keeps the raw dict, so no defaults are injected into
  the JSONB (no spurious revision diffs) and every dict consumer is untouched.
  The compiler parses with `parse_step`.
- **`ALLOWED_OPS: dict[pipeline_type, set[op]]`** lives next to the union and
  is the only place op-per-type rules live. It is the builder's old op menus,
  now also enforced on save (user decision):
  - quality: only `check`, `profile`, `filter`, `rename`, `select`, `join`;
  - eval: everything but `check`, `profile`, `aggregate`, `pivot`;
  - transform: everything but `check`, `profile` (a superset of the rule
    plan 086 adds to the validator);
  - viz: everything.
  The eval "needs a structure step" rule stays in the validator (it is a
  must-have, not a may-have). The backend validator enforces the table on
  POST/PUT (422); `GET /api/allowed-ops` exposes it, and the builder's op menus
  (`pipeline/steps-column.tsx`, `builder/steps/StepsPanel.tsx`) use it in
  place of their hand-written filters. Reads stay lenient: a pipeline or
  revision saved before a rule tightened still loads (GET, list, schedule)
  and compiles; only a re-save is refused.
- **Type generation needs no server.** `gen-api-types.sh` dumps
  `app.openapi()` from Python and feeds that to openapi-typescript.

Not doing: JSON-schema-driven step forms (Airbyte-style). Revisit when a step
is added that is pure config.

## Tasks

### 1. Discriminated union — `feature/088-step-union`
- Tests: every existing scenario pipeline round-trips; an unknown op loads as
  `UnknownStep` on read and is rejected on write; the OpenAPI schema has a
  `oneOf` for steps.
- Delete `_STEP_MODELS` and the hand dispatch in validators.

### 2. Compile on the step — `feature/088-step-compile`
- Tests: existing compiler unit tests pass unchanged.
- Move each `if op ==` branch body into its step class. `ibis_compiler.py`
  keeps the fold, the registry and the backend checks.

### 3. Writer dispatch — `feature/088-writer-dispatch`
- Replace the `isinstance` chain with a `type`-keyed dict. Tests unchanged.

### 4. Frontend on generated types — `feature/088-fe-types`
- Fix `gen-api-types.sh` to default to `http://localhost:8080/dte`.
- Regenerate. Swap the step types in `types.ts`/`editors.tsx` to the generated
  ones. Delete the duplicated types in `lib/api.ts`.
- `pnpm build` and `tsc --noEmit` both clean. A CI check fails if
  `api-types.ts` is stale (regen plus `git diff --exit-code`).

## Files

Changed: `backend/dte/models/pipeline.py`, `backend/dte/compiler/ibis_compiler.py`,
`backend/dte/compiler/interpolate.py`, `backend/dte/engine/writers/__init__.py`,
`frontend/src/lib/api.ts`, `frontend/src/lib/api-types.ts`,
`frontend/src/components/builder/steps/{types.ts,editors.tsx,summary.tsx}`,
`frontend/scripts/gen-api-types.sh`, `backend/CLAUDE.md` (how to add a step).
