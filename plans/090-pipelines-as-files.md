# 090 — Pipelines as files; the DB is an index

## Problem

A pipeline exists only as rows in `dte.pipelines` and
`dte.pipeline_revisions`.

- **No review, CI, promotion or DR.** You can't open a PR for a pipeline
  change, test it in CI, or promote dev to prod. Migration 037 wiped every
  pipeline, which is the cost of having the DB as the only copy.
- **The DAG factory reads Postgres at every parse**, and builds every DAG from
  one file (`backend/dte/airflow/dag_factory.py:20-29`). One bad config drops
  every DAG. Cost grows with revision history. A new pipeline waits about 30 s
  before it can be triggered (`airflow/trigger.py:56-69`).
- **No headless use.** The CLI only runs `dte db upgrade` (`dte/cli.py:24`),
  even though `dte/airflow/runner.py` already runs a pipeline with no stores,
  no HTTP and no Airflow.

## Decision

Files are the source of truth. The DB only indexes them.

- **Format:** one `pipelines/<id>.yaml` per pipeline. The schema is the
  plan 088 typed `PipelineBase`, so 088 lands first. Sources and destinations
  are referenced by id or `conn_id`, never inlined credentials.
- **Location:** `DTE_PIPELINES_DIR`, a directory the api-server writes to and
  the dag-processor reads from. In compose it is a shared volume. A git repo
  is optional: if the dir is a git checkout, the api-server commits on save
  (`git -C`, author = Airflow user). Pushing is left to the user or CI.
- **Revisions** come from git history when the dir is a git checkout. Without
  git, keep writing `pipeline_revisions` (today's behaviour) as the history.
  `PipelineRevision` stays, so diff and rollback keep working either way.
- **DAG factory** reads the files. One Python DAG file still covers them all,
  but each YAML parses inside its own try/except, so a broken pipeline drops
  only its own DAG and is logged as an import error.
- **The DB keeps** run results, eval sets, dashboards, the sample cache, and a
  `pipelines` index row (id, name, path, mtime) for list and search pages.
- **CLI:** `dte validate <file>`, `dte run <file> [--sample N]` (wrapping
  `runner.py`), and `dte export` (DB → files, for the one-time migration).

Not doing: multi-branch editing in the UI or a git-backed draft workflow.
Drafts stay unsaved in the editor, as today.

## Tasks

### 1. Export and validate — `feature/090-export`
- `dte export --out pipelines/` writes the latest revision of each pipeline as
  YAML. `dte validate` loads with the typed model.
- Test: export → validate round-trips every scenario pipeline unchanged.

### 2. Local run — `feature/090-cli-run`
- `dte run <file> --sample N`: build connections from Airflow env vars
  (`AIRFLOW_CONN_*`) through the existing `airflow/connections.py`, call
  `runner.run`, print the result summary.
- Test: a scenario pipeline with file source → file output runs from the CLI
  with no Postgres.

### 3. API writes files — `feature/090-file-store`
- New `FilePipelineStore` that implements the existing pipeline store protocol
  (`dte/store/base.py`) over `DTE_PIPELINES_DIR`. Optional git commit on save.
  The fakes in `tests/fakes.py` reuse it against a tmp dir, which deletes one
  duplicated fake.
- Switch with config: `DTE_PIPELINE_STORE=file|postgres` (default `postgres`
  until task 4 ships).
- Test: save → file exists with the expected YAML; with git present, a commit
  is created.

### 4. DAG factory reads files — `feature/090-dag-files`
- `build_dags()` globs `DTE_PIPELINES_DIR`. Per-file isolation. No DB at parse
  time.
- Tests: a broken YAML drops only its own DAG; parsing 1,000 files with no DB
  connection.
- Flip the default to `file`. Release note: run `dte export` once.

### 5. Docs
- `docs/user/`: "Pipelines in git" page covering the layout, CI with
  `dte validate`, and promoting by copying files between environments.

## Files

Changed: `backend/dte/cli.py`, `backend/dte/airflow/dag_factory.py`,
`backend/dte/airflow/trigger.py` (the wait shrinks to "file written"),
`backend/dte/store/__init__.py`, `backend/dte/config.py`, `docker-compose.yml`
(shared volume), `backend/tests/fakes.py`, `CLAUDE.md`, `backend/CLAUDE.md`.

New: `backend/dte/store/files.py`.

## Open questions

- Should the UI warn when the file on disk changed since the editor opened it
  (someone pushed via git)? Default: compare mtime on save and refuse with a
  409 if it changed.
- Sources and destinations: should they move to files too? Not in this plan.
  Do it only if promotion needs it.
