# 078 — Pipeline types page; writers create missing folders

## Problem

The docs never say what kinds of pipelines exist, and the getting-started run
failed: a local file destination whose folder doesn't exist (`out/`) failed
the run, because DuckDB's `COPY … TO` doesn't create folders.

## Change

- `docs/user/pipelines/types.md`: Transform, Extract (a Transform on a
  Documents source) and Quality Check, each with screenshots. In the sidebar
  under Build.
- `engine/writers/_copy.py`: local targets get their parent folder created
  before `COPY`. Test: `test_local_write_creates_missing_folders`.
- `scripts/demo/capture-docs.mjs` seeds an "Invoice extract" pipeline from
  the committed PDF corpus and captures the new shots; `ONLY=<substr>` limits
  a run to matching shots.

## Tasks (branch `feature/pipeline-types`)

1. Writer fix + test. 2. Capture script + shots. 3. Page + nav + links.

## Not done

The Extract preview screenshot: the stack was being restarted by something
else during capture. Rerun `ONLY=extract-preview node capture-docs.mjs` and
add it to the Extract section.
