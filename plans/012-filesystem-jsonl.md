# Plan 012 — Filesystem source: JSONL support

## Problem

`filesystem` source's `_load_from_fsspec` calls `json.load(f)`, so each matched file must be a single JSON value (object or array). Users who supply newline-delimited JSON (`.jsonl` / `.ndjson`) hit `Extra data: line 2 column 1` at extract time. JSONL is the more common shape for event/log fixtures, and dlt itself can't recover from a `.jsonl` extension mismatch — the loader must know.

## Non-goals

- No new source_type. This stays a `filesystem` source; only the reader inside the file-loop learns a second shape.
- No format inference beyond the file extension. If a user names a JSONL file `.json` they'll still hit the old error — the fix is to rename or set an explicit `format` in config.

## Architecture

Add a per-file dispatch in the `_json_resource` generator: decide by extension (or optional `config["format"]`) whether to `json.load` the whole file or iterate line-by-line. Empty lines are skipped. Both branches yield dicts, so downstream dlt normalisation is unchanged.

Precedence: explicit `config["format"]` > file extension > default (`json`).

Recognised values:
- `json` — one JSON value per file (object or array)
- `jsonl` (aliases: `ndjson`) — one JSON object per line, blank lines ignored

## Tasks

Single task.

### Task 1 — Add JSONL branch to `_load_from_fsspec`
- Branch: `feature/backend-filesystem-jsonl`
- `backend/dte/sources/dlt_loader.py`:
  - Extract a `_detect_format(path, config) -> "json"|"jsonl"` helper.
  - Split the file-open block: JSON uses `json.load`; JSONL iterates `f`, `json.loads(line)` per non-empty line.
- Tests in `backend/tests/unit/test_dlt_loader.py`:
  - `.jsonl` file loads and normalises nested keys with `__`.
  - Explicit `format="jsonl"` overrides `.json` extension.
  - Blank lines in a `.jsonl` file are ignored.
- Update the mounted sample `/tmp/dte-samples/nested-orders/orders.json` back to `orders.jsonl` in verification (out of scope of the code change).

## Files changed

- `backend/dte/sources/dlt_loader.py` — extended
- `backend/tests/unit/test_dlt_loader.py` — new cases
- `CLAUDE.md` — one-line note under filesystem source

## What does NOT change

- Existing single-JSON behaviour (all current tests must still pass unchanged).
- `bucket_url` / `file_glob` semantics.
- Frontend — no UI change.

## Verification

- `pytest backend/tests/unit/test_dlt_loader.py -x` green.
- Recreate `/tmp/dte-samples/nested-orders/orders.jsonl` (3 lines), update the demo pipeline's `file_glob` to `*.jsonl`, trigger → run completes, output file has 3 rows with `order__amount`, `user__address__city`, etc.
