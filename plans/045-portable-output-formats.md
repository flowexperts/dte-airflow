# Portable output formats: any format × any storage

## Context

The goal is to run the three local storage emulators (MinIO/S3, fake-gcs-server,
Azurite) and drive real pipelines against them from `localhost:8001` — reading
from one backend and writing to another, e.g. **read CSV from S3 → transform →
write Parquet to GCS**.

The emulator half already exists and works: `docker/docker-compose.storage-test.yml`,
`scripts/test-cloud-storage.sh`, and `backend/tests/integration/test_cloud_storage.py`
(plan 044) already prove **reads** from all three backends.

The blocker is the **write** side. Today destinations are one class per
format-and-location pair, and every file format is pinned to local disk:

```python
DESTINATION_CONNECTION_COMPAT = {
    "json_file": {"local_fs"}, "csv_file": {"local_fs"},
    "excel_file": {"local_fs"}, "parquet_s3": {"s3"}, ...
}
ENGINE_WRITE_SUPPORT["duckdb"] = {"local_fs", "s3", "postgres", "mysql"}
```

So you cannot write JSON to S3, anything to GCS, or anything to Azure.

**The key finding that makes this cheap:** `json_file.py`, `csv_file.py`, and
`excel_file.py` *already* write via DuckDB-native `COPY … TO '<path>'`. DuckDB's
`COPY` writes to `s3://`, `gcs://`, and `az://` URIs transparently once the
extension is loaded and a secret is created — the exact mechanism
`dte/sources/loader.py` already uses for reads. So this is **not** 15 new target
classes; it is lifting a location restriction and reusing proven secret-building
code. Only `parquet_s3.py` is the outlier (fsspec/pyarrow) and gets replaced by a
COPY-based parquet writer.

Outcome: format and location become independent axes. Any of json/csv/parquet/excel
writes to any of local_fs/s3/gcs/azure. (Arrow was considered and explicitly
dropped from scope.)

---

## Decisions taken

| Decision | Choice |
|---|---|
| Type naming | Rename to format-only: `json`, `csv`, `excel`, `parquet` (+ alembic migration, one-release aliases) |
| Storage backend detection | Infer from URI scheme in the writer — no engine signature changes |
| Live test matrix | 9 pipelines covering every cloud as reader+writer and every format as in+out |

**Why URI-scheme inference:** `_resolve()` (`api/routes/pipelines.py:430`) returns
`(destination, dest_conn.credentials)` and discards `connection_type`. Threading it
through would touch `EngineProtocol.execute`, `BaseEngine.execute`,
`DuckDBEngine.execute`, `TrinoEngine.execute`, `_resolve` and its call sites.
The destination URI is already the ground truth for where bytes land, and
connection↔type compatibility is still validated at save time.

---

## Changes

### 1. Extract DuckDB secret helpers → `backend/dte/sources/duckdb_secrets.py` (new)

Move `_build_s3_secret_sql`, `_build_gcs_secret_sql`, `_build_azure_secret_sql`,
and `_ensure_ext` out of `dte/sources/loader.py` into a shared module, so writers
don't import loader internals. `loader.py` re-imports them (no behaviour change;
existing unit tests in `tests/unit/test_loader.py` keep passing via re-export).

These already handle emulator endpoint overrides — `ENDPOINT`, `URL_STYLE 'path'`,
`USE_SSL false` for s3/gcs, and inline `BlobEndpoint=` for azure.

### 2. Models — `backend/dte/models/pipeline.py`

- Rename target classes and discriminator values:
  `JsonFileTarget`→`JsonTarget` (`"json_file"`→`"json"`), `CsvFileTarget`→`CsvTarget`,
  `ExcelFileTarget`→`ExcelTarget`, `ParquetS3Target`→`ParquetTarget` (`"parquet_s3"`→`"parquet"`).
- Keep old class names as module-level aliases (`JsonFileTarget = JsonTarget`, …) for
  one release, matching the repo's existing `DltSource`/`dlt_loader` convention.
- Accept legacy discriminator values on read via a `model_validator(mode="before")`
  that rewrites `config["type"]` legacy→new **before** union dispatch (a discriminated
  union cannot carry two values per member). Must run in both `DestinationBase._narrow_config`
  and `Destination.narrow_config()` — the latter is the ORM-hydration path, since
  `table=True` skips validators.
- Unify the path field on `path` for all four; `ParquetTarget` accepts `bucket_url`
  as a validation alias for back-compat. Give `ParquetTarget` a `fields` list for
  parity with the other three.
- `_DEST_FAMILY` keys → `json`/`csv`/`excel`/`parquet` (the `_EXT_FAMILY` /
  `_FORMAT_FAMILY` / `_FAMILY_CANONICAL_EXT` tables it builds on already exist and
  need no change — this codebase is already family-oriented).
- `DESTINATION_CONNECTION_COMPAT`: each of the four → `{local_fs, s3, gcs, azure}`.
- `ENGINE_WRITE_SUPPORT`: add `local_fs`/`s3`/`gcs`/`azure` to **every** engine, not
  just duckdb. **This is the gate that actually fires** —
  `validate_pipeline_engine_compat` in `api/routes/pipelines.py` enforces it at
  save/trigger. (`DESTINATION_CONNECTION_COMPAT` is currently defined but not
  enforced for destinations; update it anyway for consistency.)

  This required a real capability, not just a map edit: `COPY … TO` is DuckDB
  grammar, so a result living in postgres/mysql/trino previously had no working
  file-write path at all. `writers/_copy.py` now streams a non-DuckDB result
  through Arrow into a scratch DuckDB connection (`CREATE TABLE … AS SELECT` from
  a registered `RecordBatchReader`, so DuckDB spills to disk rather than buffering
  in Python) and copies from there.

### 3. Writers — `backend/dte/engine/writers/`

New shared helper `_copy.py`:

```python
_SCHEME_BACKEND = {"s3": "s3", "gcs": "gcs", "gs": "gcs",
                   "az": "azure", "azure": "azure", "abfss": "azure"}

def backend_for_uri(uri) -> str | None      # None => local filesystem
def prepare_remote(backend, uri, credentials)  # _ensure_ext + CREATE SECRET
def copy_to(backend, table, uri, format_clause) -> dict
    # create view → SELECT COUNT(*) → COPY → drop view
```

Row count comes from a separate `SELECT COUNT(*)` (the pattern all three existing
writers already use) — avoids depending on the version-specific column name of
`COPY`'s returned relation.

- Rewrite `json_file.py`, `csv_file.py`, `excel_file.py` as thin wrappers over
  `copy_to`, keeping their existing format clauses verbatim (`FORMAT JSON, ARRAY true`;
  `FORMAT CSV, HEADER`; `FORMAT xlsx, HEADER true`). Behaviour for local paths is
  unchanged — the JSON array shape that `runs/{id}/output` and `RunOutputPreview`
  depend on is preserved.
- New `parquet.py` (`FORMAT PARQUET`) replacing `parquet_s3.py`; delete the fsspec
  implementation. `s3fs` stays in `pyproject.toml` — the seeding script uses it.
- `__init__.py`: update the `isinstance` dispatch chain and pass `credentials` to
  all four file writers (currently only parquet/postgres/sql_database receive it).

### 4. Migration — `backend/alembic/versions/028_destination_type_rename.py` (new)

Rewrite `destinations.config->>'type'` legacy→new. The `destinations` table is small,
so a plain `UPDATE` is fine; note that CLAUDE.md requires `dte.alembic_util.batched_update`
for anything that *could* exceed 100k rows. **Verify during implementation** whether any
pipeline row carries an embedded output config needing the same rewrite.

### 5. Frontend — `frontend/src/`

Mechanical rename across the 7 files that reference the literals:
`lib/api.ts` (type literals, the `".json"` extension map, `isJsonFileOutput` →
`isJsonOutput`), `components/destination-form.tsx`, `components/builder/OutputPanel.tsx`,
`components/builder/DestinationPicker.tsx`, `components/run-output-preview.tsx`,
`app/(app)/destinations/new/page.tsx`, `app/(app)/preview/page.tsx`.
Then `pnpm gen:types` with the backend up on `:8001`.

Scope note: the UI only *edits* the json target today; other types render a
placeholder card. That stays true — no new destination editors in this plan.

### 6. Script — `scripts/test-cloud-storage.sh`

Make it configurable rather than adding a second script:

- `MODE="${1:-test}"` accepting `start` | `test`, defaulting to today's behaviour.
- Guard both the `trap cleanup EXIT` registration **and** the pytest invocation behind
  `[[ "$MODE" == "test" ]]`. In `start` mode: seed, print the endpoint URLs and exported
  env vars, exit 0 with containers left running.
- Health-wait and seeding run unconditionally in both modes.
- Extend seeding: currently only `orders.json` in all three (+ `orders.parquet` in MinIO).
  Add csv / parquet / xlsx variants of `orders` to all three so every source format in
  the matrix has data to read.

### 7. Tests (TDD — write these first)

- **Unit** (`backend/tests/unit/`): new target-model validation (new names accepted,
  legacy names still parse, extension/family mismatch still rejected);
  `backend_for_uri` scheme mapping; the two compat maps. Mirror the existing
  `test_writers_local.py::test_parquet_writer_memory_fs` style for writer mechanics
  via the `memory://` fsspec protocol where possible.
- **Integration** (`backend/tests/integration/test_cloud_storage.py`): extend with write
  tests per (format × cloud), gated on `MINIO_ENDPOINT` / `AZURITE_ENDPOINT` /
  `FAKE_GCS_ENDPOINT` exactly as the existing read tests are.

---

## Risk probe results (all resolved empirically, DuckDB 1.5.4)

1. **Azure writes work.** `COPY … TO 'az://…'` and `azure://` both succeed against
   Azurite. No `adlfs` dependency, no fsspec fallback — the plan's biggest risk
   evaporated.
2. **Remote `read_xlsx` works** from `s3://` and `az://`. Excel is fully portable in
   both directions, so no matrix row needed downgrading.
3. **`abfss://` fails** under connection-string auth (`AuthenticationFailed`), which is
   the form Azurite requires. Deliberately excluded from `_SCHEME_BACKEND` so a typo
   raises instead of silently misrouting.
4. **GCS writes: emulator limitation, not a code limitation.** `gcs://` writes fail
   against fake-gcs-server with HTTP 400 — it does not implement the XML API `PUT`
   DuckDB uses (a raw `PUT` returns `invalid uploadType`; only its JSON upload
   endpoint works, and there is no flag to enable the XML API). Real GCS implements
   it. The `gcs://` write path itself is verified working for all four formats
   against an XML-API-capable S3-compatible server.

   **Consequence for local testing:** the demo `conn-gcs` connection points its
   `endpoint_url` at MinIO, so `gcs://` reads *and* writes both work end to end.
   fake-gcs-server remains in the compose file and still backs the read-only
   integration tests from plan 044.

All four formats verified writing to **and** reading back from s3 and azure.

---

## Task order

1. `git worktree add ./worktrees/portable-output-formats -b feature/portable-output-formats`
2. Copy this plan to `plans/045-portable-output-formats.md` (next free number after 044).
3. Probe the four risks above against live emulators; adjust scope if azure writes fail.
4. Write failing unit tests (models, scheme mapping, compat maps).
5. Extract `duckdb_secrets.py`; confirm loader tests still green.
6. Implement model rename + aliases + legacy-type coercion + compat maps.
7. Implement `_copy.py`; rewrite the three file writers; add `parquet.py`; update dispatch.
8. Alembic `028`.
9. `uv run pytest tests/unit` green, then integration against live emulators.
10. Script `MODE` support + extended seeding.
11. Frontend rename + `pnpm gen:types`.
12. Manual verification (below).

## Verification

```bash
./scripts/test-cloud-storage.sh start          # emulators up + seeded, left running
cd backend && uv run pytest tests/unit          # fast loop
uv run pytest tests/integration/test_cloud_storage.py -m integration -v
```

Then create 3 connections (s3/gcs/azure, credentials exactly as in
`test_cloud_storage.py`) plus sources/destinations against the `dte-test`
bucket/container, and these 9 pipelines on `localhost:8001` — each writing to a
distinct key under `out/` so nothing overwrites:

| Pipeline | Read | Write |
|---|---|---|
| `pipe-csv-s3-to-parquet-gcs` | csv @ s3 | parquet @ gcs |
| `pipe-json-gcs-to-excel-azure` | json @ gcs | excel @ azure |
| `pipe-parquet-azure-to-csv-s3` | parquet @ azure | csv @ s3 |
| `pipe-json-s3-to-parquet-s3` | json @ s3 | parquet @ s3 |
| `pipe-csv-gcs-to-json-gcs` | csv @ gcs | json @ gcs |
| `pipe-excel-azure-to-parquet-azure` | excel @ azure | parquet @ azure |
| `pipe-json-s3-to-csv-azure` | json @ s3 | csv @ azure |
| `pipe-parquet-gcs-to-json-s3` | parquet @ gcs | json @ s3 |
| `pipe-csv-azure-to-excel-gcs` | csv @ azure | excel @ gcs |

Trigger each, poll `GET /api/runs/{run_id}` to `completed`, assert non-zero
`rows_written`, and confirm the object exists in the target emulator.

Teardown: `docker compose -f docker/docker-compose.storage-test.yml down -v`.
