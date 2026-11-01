# 092 — Lineage in pipeline files, then file mode by default

## Problem

Plan 090 lets `DTE_PIPELINE_STORE=file` read pipelines from
`DTE_PIPELINES_DIR/*.yaml` with no database access during DAG parsing. Plan 089
gives every run task Asset `inlets`/`outlets`. The two don't compose.

- `dag_factory._dags_from_files` builds DAGs without lineage, because
  `assets.lineage(config, sources, destinations)` needs the Source and
  Destination rows, and those are in Postgres. See the `ponytail:` note in
  `backend/dte/airflow/dag_factory.py`.
- So in file mode no pipeline emits an Asset. A pipeline scheduled
  "after upstream" (`schedule.mode: "assets"`) never runs, and Airflow
  doesn't report any error for it.
- Until this is fixed, the default can't move to `file`.

## Decision

Compute lineage when the pipeline is saved, and store it in the file. The DAG
factory reads it from there, so parsing still needs no database.

- `FilePipelineStore.save` (and `dte export`) adds a top-level
  `lineage: {inlets: [...], outlets: [...]}` to the YAML. It is computed with the
  existing `assets.lineage()`, using the Source and Destination rows the API
  already has.
- `read_revision` passes `lineage` through, and `_dags_from_files` calls
  `_dag_for(rev, rev.lineage.inlets, rev.lineage.outlets)`.
- `lineage` is derived data. `PipelineBase` ignores it when the file is read
  back into the model, and the model never writes it.
- **Known staleness:** editing a Source or Destination's connection or table
  doesn't rewrite the pipeline files that use it. Fix it in the same plan: on
  Source/Destination save, re-save each file-mode pipeline that references it.
  Only lineage is rewritten, so there is no new revision.
- `dte validate` warns, without failing, when a file has no `lineage` key (for
  example, hand-written YAML). `dte export` always writes one.

Not doing: resolving lineage from Airflow connections at parse time. That's a
DB or secrets read per parse, which is what 090 removed.

## Tasks

TDD. One worktree off `dte-airflow`: `feature/092-file-mode-lineage`.

### 1. Lineage in the file
- Tests: saving a file-mode pipeline writes `lineage` matching
  `assets.lineage()`; reading it back into `Pipeline` ignores the key; a
  round-trip doesn't change the revision hash except when lineage changes.

### 2. DAG factory reads it
- Tests: in file mode, a DAG's run task has the stored inlets/outlets; a file
  without `lineage` still builds, with none; parsing still makes no DB
  connection (keep 090's guard test).
- Remove the `ponytail:` note.

### 3. Keep it fresh
- Tests: changing a Destination's table rewrites `lineage.outlets` in every
  pipeline file that writes to it.

### 4. Flip the default
- `DTE_PIPELINE_STORE` defaults to `file`. Release note: run `dte export` once.
  A compose bring-up with a seeded pipeline must show its DAG and Asset in
  Airflow.
- Decide separately whether compose mounts `DTE_PIPELINES_DIR` as a git
  checkout by default.

## Files

Changed: `backend/dte/store/files.py`, `backend/dte/airflow/dag_factory.py`,
`backend/dte/cli.py`, `backend/dte/api/routes/sources.py` and
`destinations.py` (re-save on change), `backend/dte/config.py` (task 4),
`backend/dte/store/CLAUDE.md`, `docs/user/pipelines/in-git.md`.
