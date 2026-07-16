# 019 — Excel (.xlsx) support: source + destination

## Context

DTE currently supports CSV end-to-end (source, destination, preview) but
has zero Excel support. The goal is for `.xlsx` to work exactly like
`.csv` — pick a file in a filesystem-family source, or write to an
`.xlsx` destination. Sheet handling stays implicit (first sheet only)
to keep parity with the "one file, one stream" model. Multi-sheet
support can come as a follow-up if anyone asks.

Implementation uses **DuckDB's `excel` extension** (`INSTALL excel;
LOAD excel;`). This matches the existing filesystem loader pattern
(one execution context, `CREATE OR REPLACE VIEW … AS SELECT * FROM
read_xlsx(...)`) and avoids adding `openpyxl`/`xlsxwriter` to backend
deps. DuckDB ≥1.2 is required — confirm the current pin during
implementation.

## Current state (from code walk)

- `.csv` / `.tsv` detected in `backend/dte/sources/loader.py:18-43`
  (`_CSV_EXTS`, `_detect_format`), dispatched to `read_csv_auto` at
  `loader.py:62-63`. Same code path serves `filesystem`, `s3`, `gcs`,
  `azure`.
- `CsvFileTarget` in `backend/dte/models/pipeline.py:364-367`; part of
  the `OutputTarget` discriminated union; writer at
  `backend/dte/engine/writers/csv_file.py`.
- Writer dispatch in `backend/dte/engine/writers/__init__.py:18-42`.
- Output preview reads csv via pandas in
  `backend/dte/api/routes/runs.py:59-62`; frontend `SUPPORTED` set at
  `frontend/src/components/run-output-preview.tsx:7`.
- Destination form connection compat map:
  `backend/dte/models/pipeline.py:467` (`"csv_file": {"local_fs"}`);
  frontend mirror in `frontend/src/components/destination-form.tsx:25-31`.

## Changes

### Backend — read path (`.xlsx` source)

**`backend/dte/sources/loader.py`**
- Extend `_FileFormat` literal to include `"excel"`.
- Add `_EXCEL_EXTS = (".xlsx",)` (skip legacy `.xls`; DuckDB's extension
  only handles `.xlsx`).
- Update `_detect_format` to return `"excel"` for `.xlsx`.
- In `_duckdb_reader_call` (the dispatch that maps format → DuckDB
  reader), add the `excel` branch returning `f"read_xlsx('{path}')"`.
- In whichever loader helper runs `INSTALL`/`LOAD` (grep for `INSTALL
  httpfs` — same location), install+load `excel` lazily when the format
  is `excel`. Idempotent — `INSTALL excel; LOAD excel;` is a no-op on
  repeat.

**`backend/dte/models/pipeline.py`**
- Extend the source-side `_FileFormat` literal referenced by
  `FilesystemSourceConfig.format` to include `"excel"`.

### Backend — write path (`.xlsx` destination)

**`backend/dte/models/pipeline.py`**
- Add `ExcelFileTarget(BaseModel)` mirroring `CsvFileTarget`
  (`type: Literal["excel_file"]`, `path: str`,
  `fields: list[OutputField] = []`).
- Extend the `OutputTarget` discriminated union with
  `ExcelFileTarget`.
- Add `"excel_file": {"local_fs"}` to
  `DESTINATION_CONNECTION_COMPAT`.

**`backend/dte/engine/writers/excel_file.py` (new)**
- Signature parallel to `csv_file.write`. Body:
  ```python
  con.execute("INSTALL excel; LOAD excel;")
  con.execute(f"COPY ({sql}) TO '{target.path}' (FORMAT xlsx, HEADER true)")
  ```
  Route through the shared DuckDB backend rather than pandas — no
  round-trip through Python. Return `{"rows_written": ...}` in the same
  shape as `csv_file.write`.

**`backend/dte/engine/writers/__init__.py`**
- Dispatch `ExcelFileTarget` → `excel_file.write`.

### Backend — output preview

**`backend/dte/api/routes/runs.py`**
- Extend the CSV branch (lines 59-62) with an `elif
  path.endswith(".xlsx")`. Prefer DuckDB `read_xlsx(...) LIMIT N` for
  the read to avoid pulling in `openpyxl`. Fall back to
  `pd.read_excel(..., nrows=limit, engine="openpyxl")` only if the
  existing CSV branch uses pandas for a reason (verify during
  implementation) — in that case add `openpyxl` to
  `backend/pyproject.toml`.

### Frontend

**`frontend/src/lib/api-types.ts`** — regen via `pnpm gen:types` after
backend changes land (backend must be up on `:8001`).

**`frontend/src/components/run-output-preview.tsx`**
- Extend `SUPPORTED` set (line 7) to include `"excel_file"`.

**`frontend/src/components/destination-form.tsx`**
- Add `excel_file` to the destination type picker and the
  connection-compat map (mirrors `csv_file`).

**Builder inline destination editor — deliberately out of scope.** The
existing `OutputPanel` only edits `json_file`; that gap exists for CSV
too and users work around it via `/destinations`. Flag as a follow-up
if the user wants it inline.

### Docs

**`CLAUDE.md`**
- Update the "First-class sources and destinations" section to list
  `excel_file` in the OutputTarget enumeration.
- Update the "Full data flow" callouts to mention `.xlsx` alongside
  `.csv`.

### Tests (TDD — write these first)

- `backend/tests/unit/test_loader.py` (or wherever `_detect_format` is
  tested): add cases for `.xlsx` → `"excel"`.
- Integration test with a fixture `.xlsx` under
  `backend/tests/fixtures/`: load a small workbook and assert row
  count + column names.
- Writer test (`test_writer_excel.py` or extend existing): compile a
  trivial pipeline into `ExcelFileTarget`, assert file exists and
  round-trips with expected rows.
- Skip if `DATABASE_URL` isn't set — follow the existing integration
  skip pattern.

## Verification

1. `docker compose up -d --build` — confirm build succeeds with no dep
   surprise (only relevant if `openpyxl` ends up being added).
2. Drop a two-column `orders.xlsx` in `/tmp/dte-samples/`.
3. Create a filesystem connection + source pointing at
   `/tmp/dte-samples` with `file_glob=*.xlsx`.
4. `POST /api/schema/infer` on that source — inferred columns come back.
5. Create an `excel_file` destination at
   `/tmp/dte-samples/out/orders.xlsx`.
6. Build a pipeline with source + no steps + destination.
7. `POST /api/pipelines/{id}/trigger`; poll `/api/runs/{run_id}` until
   `completed`.
8. Open the written `.xlsx` in a spreadsheet tool — verify rows.
9. Hit `/api/runs/{run_id}/output?limit=5` and confirm rows come back
   (means preview branch works).
10. Frontend: open `/pipelines/{id}` → "Dry run" → `JsonCell` renderer
    displays rows.
11. `cd backend && uv run pytest -m "not integration"` — new unit
    tests green.
12. `cd frontend && pnpm exec tsc --noEmit` — no new type errors.

## Files touched (summary)

- `backend/dte/sources/loader.py`
- `backend/dte/models/pipeline.py`
- `backend/dte/engine/writers/excel_file.py` (new)
- `backend/dte/engine/writers/__init__.py`
- `backend/dte/api/routes/runs.py`
- `backend/pyproject.toml` (only if the preview needs `openpyxl`)
- `backend/tests/unit/test_loader.py` (+ new writer/integration test)
- `backend/tests/fixtures/*.xlsx` (small workbook)
- `frontend/src/lib/api-types.ts` (regen)
- `frontend/src/components/run-output-preview.tsx`
- `frontend/src/components/destination-form.tsx`
- `CLAUDE.md`
