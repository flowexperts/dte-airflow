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
- `GET /pipelines/{id}/diff` adds `yaml_diff`: a unified diff from stdlib
  `difflib` over the two YAMLs. No diff library in the frontend.
- Revision page: a **YAML** panel and a **Changes** panel (the diff against
  the previous revision, found from the revision list) under the canvas.
- History tab diff: the YAML diff renders above the structural one.

## Tasks

### 1. Backend — `feature/093-revision-yaml`
- Tests: the revision GET returns `yaml` that loads back to `config`; the diff
  carries `-`/`+` lines for a renamed pipeline; identical revisions give an
  empty diff.

### 2. Frontend — same branch
- `YamlDiff` component (one line per diff line, coloured by prefix), used by
  `DiffView` and the revision page. `YamlBlock` for the plain YAML.
- Revision page fetches the revision list to find the predecessor.

## Files

Changed: `backend/dte/api/routes/pipelines.py`,
`backend/tests/unit/test_pipeline_history_api.py`, `frontend/src/lib/api.ts`,
`frontend/src/components/builder/history/DiffView.tsx`,
`frontend/src/pages/pipelines/revision.tsx`.

New: `frontend/src/components/builder/history/YamlDiff.tsx`.
