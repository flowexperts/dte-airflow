# 087 — A run lives in one place

## Problem

A pipeline run shows up in two UIs, and neither links to the other.

- DTE's run page (`frontend/src/pages/runs/detail.tsx`) polls
  `/api/runs/{id}`. Its step `Timeline` is a stub ("events not recorded yet").
  It has no link to the Airflow DAG run or task log: grepping `frontend/src`
  for `/dags` or `dag_run` finds nothing.
- Airflow's task log gets one `step N op: status` line per step
  (`backend/dte/airflow/operators.py:78`). Those lines are written at compile
  time, not when the work actually happens, so they carry no timings.
- `feature/airflow-task-logs` already built timed, grouped task logs and a
  "DTE Run" tab on Airflow's DAG run page. It never merged, is now 79
  commits behind, and its plan file `070-airflow-task-logs.md` clashes with
  main's `070-run-dates-retries-alerts.md`.

## Decision

Airflow is the run UI: it owns history, retries, logs and the grid. DTE adds
only what Airflow can't show (step metrics, quality results, sample output),
as a tab on Airflow's DAG run page. DTE's own run page becomes a thin view
that links out. There is no second run history.

## Tasks

### 1. Revive the branch — `feature/087-task-logs`
- New worktree off `dte-airflow`. Cherry-pick or re-apply `b090921` (grouped
  logs) and `c231b59` (DTE Run tab) from `feature/airflow-task-logs`.
  Rebasing across 79 commits isn't worth it.
- Move its plan content into this file. Delete the clashing
  `070-airflow-task-logs.md`.
- Test: an operator run emits one log group per step, with a duration line.

### 2. Step timings where the work happens — same branch
- Record step start/end around the point where the fold actually executes
  (the write in `runner.py`, eager steps in `duckdb_engine.py`), not during
  compile. Store them in `run_results.events`, which is already JSONB.
- The DTE run page `Timeline` reads `events`, and the stub goes away.

### 3. Deep links — `feature/087-deep-links`
- `run_results` already holds `dag_id`/`run_id` (verify; if not, add them in
  `airflow/results.py`).
- The run page gets "Open in Airflow" (dag run grid) and "Task log" links.
  Each `FailedSteps` row links to the task log, anchored to its step group.
- Test: a frontend unit test that the link URL is built from `dag_id`/`run_id`.

### 4. Remove the duplicates
- Drop DTE run-list features that Airflow's grid already gives you (status
  filters, retry). Keep the pipeline-scoped "last N runs" summary.

## Files

Changed: `backend/dte/airflow/operators.py`, `backend/dte/airflow/runner.py`,
`backend/dte/airflow/results.py`, `backend/dte/airflow/plugin.py`,
`frontend/src/pages/runs/detail.tsx`, `frontend/src/components/run/failed-steps.tsx`,
`frontend/src/plugin.tsx`.

Deleted: `plans/070-airflow-task-logs.md` (on the old branch), then the
`feature/airflow-task-logs` branch and worktree once this merges.

## Task log shape (folded in from the old `070-airflow-task-logs.md`)

ibis is lazy, so `compile_pipeline` fires "started/completed" for every lazy
step within milliseconds; the real work happens in `engine.execute()`.
`run_pipeline(..., log=)` (the operator passes `self.log`) writes the run as
timed phases, using Airflow's `::group::` / `::endgroup::` markers:

- **Header**: pipeline type, engine, source and step counts, param *keys*
  only (values may be secrets).
- **Load source** (one group each): connection type, table, columns.
- **One group per step**: columns after the step, its SQL, enrichment stats
  for eager steps, and `step #N op took Xs`. The compiler reports schema and
  SQL after "completed", so a step's group closes when the next one starts.
- **Final SQL** (group), then **execute + write** with rows written.
- **Quality**: one line per check, INFO/WARNING/ERROR by verdict.
- **Eval**: compile, execute, score phases and the numeric scores.

Each phase also reaches `on_event` as `(None, title, status, msg)`, so
`run_results.events` holds steps *and* phases (`step_index: null`).

### Deliberately not doing
- Per-step row counts: each is a separate query, so cost grows with steps.
- Anchoring a failed step to its log group: Airflow numbers groups, it does
  not name them, so `FailedSteps` links to the task log page.
- A step-timing UI that assumes `check`/`profile` run in transform
  pipelines (plan 086 makes them invalid there).
