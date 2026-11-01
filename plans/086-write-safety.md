# 086 — Don't publish bad data, don't eat the box

## Problem

Plan 082 handles merge-without-key and DB writers loading the whole result
into memory. This plan covers the run-path problems 082 leaves out:

- **Transform pipelines accept `check` and `profile` steps and drop their
  results.** The builder hides `category: "quality"` ops for transform and
  eval pipelines, but the API doesn't. `runner.py` compiles a transform with
  no `on_quality_result`, so a failing check still reports `completed`.
- **Quality contracts run after the write** (`dte/airflow/runner.py:106-112`). A
  `failed_quality` run has already overwritten the destination with the rows
  the check rejected.
- **DuckDB has no resource limits.** `ibis.duckdb.connect()` is called with no
  `memory_limit`, `threads` or `temp_directory` (`dte/engine/registry.py:69`,
  `dte/engine/duckdb_engine.py:26`). Each concurrent task and each preview
  assumes it can use 80% of host RAM.
- **File outputs are not atomic.** `COPY … TO` writes straight to the final
  path (`dte/engine/writers/_copy.py`), so a failure halfway through leaves a
  truncated file that readers will pick up.
- **Probable wrong branch for pushdown-to-file.** `DuckDBEngine.execute`
  always passes `self._con` (`duckdb_engine.py:34`). `copy_to` then sees a
  DuckDB backend (`_copy.py:56`) even when the table is bound to Postgres, and
  never reaches the Arrow-staging branch that was written for this case
  (`_copy.py:63-80`). Unverified.
- **`run_timeout_seconds` is defined but never read** (`dte/config.py:29`).
  Previews have no timeout at all. Plan 084 task 1 adds the thread pool;
  timeouts are still missing.

## Decision

| Concern | Fix |
|---|---|
| Quality ops in transform/eval | Decided: transform and eval pipelines may not have `check` or `profile` steps. `PipelineBase` rejects them on POST/PUT (422), next to the quality-pipeline `aggregate`/`pivot` rule. Reads stay lenient, so an older revision with a check step still loads and runs (its result is still dropped). |
| Contracts after write | `quality_contracts` with `phase: "pre"` (the default) run on the compiled result **before** the write. Contracts that need the written table stay after it as `phase: "post"`. Inline check steps aren't part of this; task 0 removes them from transforms. |
| Memory | One `connect_duckdb()` helper sets `memory_limit`, `threads` and `temp_directory` from config. Every `ibis.duckdb.connect()` call goes through it. |
| Atomic files | Write to `<path>.tmp-<run_id>`, then rename. For object stores, write to a temp key, then copy and delete (fsspec), or accept a partial file and document it. |
| Pushdown to file | A failing test first, then pass `con` only when the table is bound to it. |
| Timeouts | Wire `run_timeout_seconds` as the default `execution_timeout`. Preview gets `preview_timeout_seconds` (default 30) via `anyio.fail_after` around 084's thread-pool call. |

Not doing: staging-table swap for DB destinations. That needs 082's ATTACH
writers first. Revisit in 082 step 2.

## Tasks

TDD in every step. Each step is its own worktree off `dte-airflow`.

### 0. No quality ops outside quality pipelines
- Test: POST/PUT a transform with `check`, a transform with `profile`, an eval
  with `check` → 422. Quality still accepts both. A saved transform revision
  with a check still reads and runs.
- `models/pipeline.py`: reject in `PipelineBase._validate_steps`.

### 1. B5 regression — `feature/086-pushdown-file`
- Scenario test: `sql_database` (Postgres) source → `parquet_file` output.
  Expected to fail today.
- Fix: in `DuckDBEngine.execute`, pass `self._con` only if
  `table._find_backend() is self._con`.

### 2. DuckDB limits — `feature/086-duckdb-limits`
- Test: `connect_duckdb()` applies the settings (`SELECT current_setting('memory_limit')`).
- Add `duckdb_memory_limit`, `duckdb_threads` and `duckdb_temp_dir` to `dte/config.py`.
- Replace bare `ibis.duckdb.connect()` in `engine/registry.py`,
  `engine/duckdb_engine.py`, `engine/writers/_copy.py` and the preview path.
  Find every call with
  `ast-grep --lang python -p 'ibis.duckdb.connect($$$)'`.

### 3. Contracts before publish — `feature/086-checks-first`
- Scope: `quality_contracts` only. Inline check steps are task 0.
- Test: a pipeline with a failing blocking contract leaves the destination file
  untouched.
- `runner.py`: evaluate pre-write contracts on the compiled table, then write.
  Contract model gets `phase: "pre" | "post"` (default `pre`). Existing saved
  contracts read as `pre`, which is lenient on read.

### 4. Atomic file writes — `feature/086-atomic-files`
- Test: inject a failure into `COPY`, and the final path must not exist or
  must keep its old contents.
- `_copy.py`: temp path plus `os.replace` locally, fsspec `mv` for object stores.

### 5. Timeouts — `feature/086-timeouts`
- After 084 merges. Test: a slow fake source returns 504 from preview within
  the configured timeout.
- `dag_factory.py`: `execution_timeout` falls back to `run_timeout_seconds`.

## Files

Changed: `backend/dte/airflow/runner.py`, `backend/dte/airflow/dag_factory.py`,
`backend/dte/config.py`, `backend/dte/engine/duckdb_engine.py`,
`backend/dte/engine/registry.py`, `backend/dte/engine/writers/_copy.py`,
`backend/dte/api/routes/pipelines.py`, the quality contract model in
`backend/dte/models/pipeline.py`, `backend/CLAUDE.md`.

New: tests per step.
