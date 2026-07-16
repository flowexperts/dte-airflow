# 020 — Destination path/extension guardrails

## Context

Destinations are typed by their `type` field, not by the file extension
on `path`. This lets you save a `json_file` destination at
`/tmp/out/orders.csv` and get JSON in a `.csv`-named file — surprising
enough that a user hit it during Excel scoping. The three-tier model
(Connection → Destination → Pipeline) is right; the gap is that nothing
correlates `type` with the on-disk extension.

Goal: prevent the footgun without changing the model. Users get a clear
inline hint at edit time, obvious autofill when they omit the
extension, and a hard save-time error if the two disagree. Same idea
should apply to source `file_glob` where a matching format hint helps.

## Current state

- `OutputTarget` union in `backend/dte/models/pipeline.py` covers
  `json_file`, `csv_file`, `parquet_s3`, `postgres`, `sql_database` (and
  `excel_file` post-019).
- Writer dispatch (`backend/dte/engine/writers/__init__.py`) picks the
  writer by `type`; path is opaque to the dispatcher.
- Frontend destination form
  (`frontend/src/components/destination-form.tsx`) has a type picker and
  a path input with no format-aware hint.
- Filesystem source config (`FilesystemSourceConfig` in
  `backend/dte/models/pipeline.py`) has an explicit `format` override
  that already sidesteps extension mismatch on the source side, but the
  `file_glob` field itself has no matching hint.

## Design

**Canonical extension map (backend, single source of truth):**

```python
# backend/dte/models/pipeline.py
_DEST_EXTENSION = {
    "json_file":  ".json",
    "csv_file":   ".csv",
    "excel_file": ".xlsx",     # only if 019 landed
    "parquet_s3": ".parquet",
}
```

Types with no on-disk file (`postgres`, `sql_database`) are excluded —
the check is a no-op for them.

**Backend validation.** Add a `model_validator` on each file-shaped
target (or a shared base) that raises `ValueError` when the path's
extension differs from the canonical mapping:

```
config path 'orders.csv' does not match destination type 'json_file'
(expected '.json'). Rename the file or change the type.
```

Case-insensitive suffix match. `.jsonl`/`.ndjson` accepted as aliases
for `json_file` since dlt can produce either. Missing extension is
rejected too — no silent behavior. This fires on both `POST` and
`PUT /api/destinations`.

**Frontend UX.**

- `frontend/src/components/destination-form.tsx`: derive the expected
  extension from the selected type, show it as `Field` hint copy
  (`"expected extension: .csv"`), and validate on submit before hitting
  the API so the error surfaces inline rather than as a 422 round-trip.
- When the user types a path with no extension and blurs the input,
  auto-append the canonical extension. Do **not** auto-rewrite an
  extension the user typed — that's their intent to preserve.
- Same treatment for the (out-of-scope-today) inline
  `OutputPanel` in the pipeline builder if/when it gains a type picker.

**Source-side symmetry.** `FilesystemSourceConfig.file_glob` gains a
soft frontend hint: if `format` is set and `file_glob` ends in a
different extension, show a subtle warning under the input (not an
error — glob semantics are flexible). Backend stays unchanged; the
`format` override already handles the ambiguous case.

## Changes

### Backend

**`backend/dte/models/pipeline.py`**
- Add `_DEST_EXTENSION` mapping.
- Add a `@model_validator(mode="after")` on each of `JsonFileTarget`,
  `CsvFileTarget`, `ExcelFileTarget`, `ParquetS3Target` (or a shared
  mixin) that checks path suffix against the mapping. Accept
  `.json`/`.jsonl`/`.ndjson` as JSON aliases.

### Frontend

**`frontend/src/components/destination-form.tsx`**
- Import a `EXPECTED_EXT` map (mirrors backend); render as `Field` hint
  when a file-shaped type is selected.
- On blur of the path input, if the value is non-empty and has no
  extension, append the canonical one.
- On submit, run the same check as the backend so the user sees the
  error before the round-trip.

**`frontend/src/components/builder/sources/FilesystemSourceEditor.tsx`**
- Soft hint under `file_glob` when `format` is explicit and disagrees
  with the trailing extension of the glob.

### Tests (TDD)

- `backend/tests/unit/test_pipeline_spec.py`: mismatched-extension
  cases for each `*_Target` type — expect `ValidationError` with a
  message naming both the seen and expected extension.
- Alias cases: `.jsonl` and `.ndjson` accepted for `json_file`.
- No-op cases: `postgres`, `sql_database` destinations pass regardless
  of `path`-like fields.
- Frontend: no new unit tests (form validation lives in a hook we can
  unit-test with `vitest` if the vitest deps ever get installed);
  otherwise verify manually.

## Verification

1. `POST /api/destinations` with
   `{"type":"json_file","path":"/tmp/out/orders.csv","connection_id":"..."}`
   → 422 naming both extensions.
2. Same payload with `path=/tmp/out/orders.jsonl` → succeeds.
3. UI: create a destination, pick "CSV file", clear the path, type
   `orders`, blur → path becomes `orders.csv`. Change type to "JSON
   file" → hint updates to `.json`; existing `.csv` value stays until
   the user edits (no silent rewrite).
4. Existing pipelines that already have mismatched destinations don't
   break on read — the validator only runs on save (Pydantic runs on
   parse; `GET` responses parse too, so we may need to loosen to a
   warning field rather than a hard raise on read paths — decide
   during implementation by checking whether the response models
   round-trip through the same class). If the round-trip is strict,
   fall back to a `model_validator(mode="before")` on save-time
   entrypoints only.
5. `uv run pytest -m "not integration"` green.
6. `pnpm exec tsc --noEmit` green.

## Files touched (summary)

- `backend/dte/models/pipeline.py`
- `backend/tests/unit/test_pipeline_spec.py`
- `frontend/src/components/destination-form.tsx`
- `frontend/src/components/builder/sources/FilesystemSourceEditor.tsx`

## Explicitly out of scope

- Renaming existing files on disk when the type changes.
- Auto-migrating mismatched destination rows in the DB — flag them via
  a `scripts/audit_destination_extensions.py` in a follow-up if the
  audit finds enough drift to warrant it.
