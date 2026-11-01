# 093 — Every revision shows its YAML and a YAML diff

## Problem

A revision is shown only as a read-only canvas, and two revisions are
compared through a structural diff that prints whole steps as JSON. The YAML a
pipeline becomes on disk (plan 090, `dte export`, file mode) is never visible
in the UI, so what a reviewer sees in a git PR doesn't match anything in DTE.

## Decision

- The YAML is the backend's `store/files.dump_yaml(revision.config)`, the same
  function `dte export` and `FilePipelineStore` use, so the UI shows
  byte-for-byte what lands in the file. No YAML library in the frontend.
- `GET /pipelines/{id}/revisions/{rev}` adds `yaml`.
- `GET /pipelines/{id}/diff` adds `yaml_diff`: hunks of before/after line
  pairs (`pipelines/diff.side_by_side`, stdlib `difflib`, 3 lines of
  context). No diff library in the frontend.
- **The read-only spec shows what changed.** New and edited steps are tinted
  green with an `added`/`changed` label; removed steps are struck red rows
  where they sat. `step_marks` (on the diff response) matches steps by
  content with `difflib`, so inserting one step marks one step — the
  positional `diff_pipeline` would mark every step after it.
- **YAML on click.** A `YAML` button in the revision banner opens the panel;
  the page then splits 50/50, spec | **Changes** (split before | after YAML
  diff) and **YAML** tabs. Each
  line pair is one grid row, so wrapped lines keep both sides aligned.
- **The History list carries no diff.** No pick-two selection; a row opens
  the revision. The JSON structural diff (`DiffView`) is deleted.

## Tasks

### 1. Backend — `feature/093-revision-yaml`
- Tests: the revision GET returns `yaml` that loads back to `config`; the diff
  carries `-`/`+` lines for a renamed pipeline; identical revisions give an
  empty diff.

### 2. Frontend — same branch
- `RevisionYaml` (Changes / YAML tabs) in the canvas rail slot on a revision.
  `--red-tint` / `--green-tint` tokens for changed rows.
- Revision page fetches the revision list to find the predecessor.

## Files

Changed: `backend/dte/api/routes/pipelines.py`,
`backend/tests/unit/test_pipeline_history_api.py`, `frontend/src/lib/api.ts`,
`frontend/src/components/builder/history/HistoryPanel.tsx`,
`frontend/src/components/pipeline/canvas.tsx`, `frontend/src/dte.css`,
`frontend/src/pages/pipelines/revision.tsx`.

New: `frontend/src/components/builder/history/YamlDiff.tsx`.

Deleted: `frontend/src/components/builder/history/DiffView.tsx`.
