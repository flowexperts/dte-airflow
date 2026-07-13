# Plan 014 — Native DuckDB reads for S3 / GCS / Azure

## Context

Plan 013 left S3 and GCS on the dlt+fsspec path as a follow-up. This finishes the job: swap fsspec for DuckDB's native remote readers via the `httpfs` (S3 + GCS-over-S3) and `azure` extensions. Adds `azure` as a new `source_type`. All three end up going through the same `read_json_auto` / `read_csv_auto` / `read_parquet` seam as local filesystem.

## Non-goals

- New writers. Sinks are unrelated.
- Reworking `resolve_secret()` — still the `{"env": "…"}` seam.

## Architecture

Shared helper `_load_remote_via_duckdb(source, con, secret_sql, url)` — installs the required extension, runs the `CREATE SECRET` DDL, resolves a `read_*_auto` call over the remote URL, and materialises via `CREATE OR REPLACE VIEW`.

### `CREATE SECRET` shapes

| type | keys emitted from config |
|---|---|
| `s3` | `KEY_ID`, `SECRET`, optional `SESSION_TOKEN`, `REGION`, `ENDPOINT` (`URL_STYLE 'path'` + `USE_SSL false` when endpoint is HTTP — needed for LocalStack / MinIO) |
| `gcs` | `KEY_ID`, `SECRET` — HMAC-key style. **Breaking change:** the old `credentials_json` (service-account JSON) is no longer accepted; users must issue HMAC keys or use ADC. Documented. |
| `azure` | `CONNECTION_STRING` (preferred) or `ACCOUNT_NAME` + `ACCOUNT_KEY` |

### Path form

DuckDB accepts `s3://…`, `gs://…` / `gcs://…`, `azure://…`. The `bucket_url` config already carries the scheme; `file_glob` is joined onto it and passed straight to the reader.

### Tests

The old s3 e2e test monkeypatched `fsspec.get_fs_token_paths` — that's gone. Replaced with:
- Unit tests over pure SQL-builder helpers: `_build_s3_secret_sql`, `_build_gcs_secret_sql`, `_build_azure_secret_sql`. Assert the DDL contains the right keys, quoting is safe, and env-indirection is resolved.
- Removal of the LOADERS dispatch tests for `s3`/`gcs` is fine; the new tests still assert those keys are registered.
- No live remote tests — those require credentials + endpoints and belong in `integration/`.

## Tasks

Single task, single worktree.

### Task 1 — Rewrite s3/gcs, add azure
- Branch: `feature/backend-object-storage-native`
- `backend/dte/sources/dlt_loader.py`:
  - Add `_build_s3_secret_sql(config) → sql`, `_build_gcs_secret_sql(config) → sql`, `_build_azure_secret_sql(config) → sql`.
  - Add `_load_remote_via_duckdb(source, con, extension, secret_sql) → ibis.Table`.
  - Rewrite `_load_s3`, `_load_gcs`; add `_load_azure`. Register `azure` in `LOADERS`.
  - Delete the old `_build_s3_storage_options` / `_build_gcs_storage_options` helpers and the fsspec-only `_load_from_fsspec` path.
- `backend/tests/unit/test_dlt_loader.py`:
  - Replace the fsspec monkeypatch e2e for s3 with SQL-builder unit tests.
  - Same for gcs — drop the `credentials_json` cases; add HMAC-key + env-indirection cases.
  - Add azure tests: connection_string, env-indirection, account_name/key pair.
  - Add dispatch test for `azure`.
- `CLAUDE.md`: refresh the source_type dispatch table (add azure; update gcs auth story).

## Files touched

- `backend/dte/sources/dlt_loader.py`
- `backend/tests/unit/test_dlt_loader.py`
- `CLAUDE.md`

## Verification

- `uv run pytest tests/unit/test_dlt_loader.py -x` green (all builder + dispatch tests).
- `docker compose up` — stack starts.
- Manual smoke (optional): with real AWS creds, POST `/api/schema/infer` with an `s3` source. Not required for merge.

## Breaking change

Any pre-existing `gcs` sources that use `credentials_json` will fail to load — DuckDB's GCS auth uses HMAC keys, not service-account JSON. Users must reissue as HMAC key + secret. Called out in the CLAUDE.md gcs entry.
