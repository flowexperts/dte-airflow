# Plan 055 — The comparison matrix belongs to the eval pipeline

*(On implementation, copy this to `plans/055-matrix-on-the-eval-pipeline.md`
per the repo convention.)*

## Context

An eval run **is** a comparison run. The object model already agrees — a sweep
expands a matrix into one run per cell — but the matrix itself is *transient*:
it lives only inside the Compare wizard, is posted once to
`POST /eval-sets/{id}/sweep`, and is never stored.

Consequences, all observed:

- **You cannot reopen a comparison, change one axis and re-run it.** You start
  over from an empty wizard and get a fresh set of variant pipelines each time.
  That is how `demo_eval_strict` accumulated twelve variants, three of them
  nested junk.
- **The eval pipeline builder cannot express what an eval pipeline is for.**
  It edits one `structure` step with one `provider`, while the thing the user
  actually wants to declare is "these three configs, against this corpus".
- The Compare wizard is already a multi-provider config editor. It is simply
  not persisted, so its output is a launch rather than a saved intent.

**Intended outcome:** an eval pipeline carries its own comparison matrix,
edited in the builder alongside its steps, saved with it, and re-runnable.
The wizard goes away; its two load-bearing rules move into the builder.

## Scope

Decided with the user:

- **The matrix is persisted; sweep cells stay real pipelines.** The variant
  machinery (`prune_cells`, `root_pipeline_id`, `variant_name`,
  `isSweepVariant`, ~24 frontend references) survives untouched this round.
  Collapsing cells so they stop being pipelines is the obvious follow-on and
  is where the migration risk lives — existing variants own real run history.
  Not in this plan.
- **The builder panel replaces the wizard.** One surface for configuring a
  comparison, and it is the pipeline the comparison belongs to.

## Design

### `matrix` on the pipeline

`PipelineBase.matrix: dict[str, list] | None = None` (`dte/models/pipeline.py`),
nullable JSONB column, migration `036`. Absent means N=1 — an ordinary single
config eval run, which stays first-class because it is what a nightly
regression check schedules.

**Rejected at save on a non-eval pipeline** (422). A matrix on a transform
pipeline would be stored, ignored, and silently do nothing — the exact
silent-no-op class this codebase keeps closing.

**Axes are validated at save**, not first at spend. Reuse the existing
authority in `dte/evals/sweep.py` — `_CREATABLE_AXES` and the `apply_cell`
guard — so a typo'd axis 422s when the pipeline is saved rather than after a
sweep has been estimated, launched and paid for.

### The sweep route reads the stored matrix

`SweepRequest.matrix` stays, and stays authoritative when supplied — the
estimate/confirm pair posts exactly what the user is looking at. When the body
omits it, fall back to the pipeline's stored `matrix`. That one line is what
makes "an eval run is a comparison run" true for callers that do not carry a
body: schedules, and any future re-run affordance.

### `MatrixPanel` in the builder

New `components/evals/matrix-panel.tsx`, rendered by `canvas.tsx` as a block
only when `pipeline_type === "eval"`, directly above the steps it varies. It
edits through the existing `patch({ matrix })` and saves with the rest of the
pipeline — no separate save button, no second dirty state.

Reuses `lib/compare-matrix.ts` unchanged for `buildMatrix`, `cellCount` and
`regexAvailability`. Adds one pure function, **`draftFromMatrix`** — the
inverse of `buildMatrix` — because a persisted matrix must round-trip back
into the chip state that produced it. Without it, reopening a saved
comparison shows an empty panel and re-saving silently discards axes.

The `PROVIDERS` / `MODELS` tables currently sit inside `compare-wizard.tsx`;
lift them into `lib/compare-matrix.ts` so the panel and the cost estimator
name models identically.

### What must survive the wizard's deletion

Four behaviours in `compare-wizard.tsx` are load-bearing and each was written
against a real failure. They move into the panel:

1. **Estimate before Run.** A cartesian product over a corpus is real money.
   Run stays disabled until a cell count and price have been seen — and the
   condition is stated on screen, per `DESIGN.md`: *no disabled button whose
   enabling condition isn't stated somewhere on screen*.
2. **Calls are a ceiling, not a forecast.** Extraction is cached by document
   content, so re-running an evaluated cell costs nothing. The copy saying so
   comes across verbatim.
3. **Provider gating on configuration** (`GET /api/providers/structure`).
   A provider with no key is disabled and names the variable to set. Derived,
   never synced into the draft by an effect — that was a lint failure
   (`react-hooks/set-state-in-effect`) and would fight the user's clicks.
4. **`regex` gated on per-field patterns.** Without a `pattern` per field the
   provider returns nothing on every row and the cell scores ~0, which reads
   as "regex is bad at this" rather than "regex was never configured".

### The button

The user left naming to me. The action is labelled by what it will produce,
so the count is visible before the click rather than in a confirmation:

- N ≥ 2 → **`Compare 3 configs`**
- N = 1 → **`Run eval`**

`Estimate` sits beside it and carries `variant="primary"` until an estimate
exists, at which point primary moves to the run button — the emphasis follows
the step you can actually take (the fix already made once for this pair).

### `Compare…` on a transform pipeline

Still needed — that is how a transform pipeline gets an eval twin at all. Its
job narrows to creation: `POST /pipelines/{id}/as-eval` +
`POST /eval-sets:for-pipeline` (both idempotent), then navigate to the twin,
where the matrix panel is. The toast says what happened, because being moved
to a different pipeline without explanation is disorienting:
*"Eval twin created — configure the comparison here."*

## Files

**Backend**
- `dte/models/pipeline.py` — `matrix` field, non-eval rejection, axis validation
- `alembic/versions/036_pipeline_matrix.py` — `pipelines.matrix jsonb null`
- `dte/api/routes/evals.py` — sweep falls back to the stored matrix
- `tests/unit/test_pipeline_matrix.py` *(new)*

**Frontend**
- `lib/compare-matrix.ts` — `draftFromMatrix`; lift `PROVIDERS` / `MODELS`
- `lib/compare-matrix.test.ts` — round-trip cases
- `components/evals/matrix-panel.tsx` *(new)*
- `components/pipeline/canvas.tsx` — `matrixBlock`, eval only
- `components/pipeline/compare-button.tsx` — create twin, then navigate
- **Deleted:** `components/evals/compare-wizard.tsx`

**Docs** — `CLAUDE.md`, the Compare section: the matrix is a property of the
pipeline; the wizard is gone.

## Tasks

Worktree per CLAUDE.md, and note the fresh-worktree setup now documented there
(`.env`, `pnpm install`, `next typegen`, `uv venv`).

TDD — failing tests first at each step.

1. `matrix` on the model + migration `036`; tests for the non-eval 422 and the
   bad-axis 422.
2. Sweep falls back to the stored matrix; test that an empty body still
   expands the saved cells.
3. `draftFromMatrix` + round-trip vitest (`buildMatrix(draftFromMatrix(m))`
   equals `m` for every axis, including the empty matrix).
4. `MatrixPanel`, carrying all four surviving behaviours.
5. Wire into `canvas.tsx`; rework `CompareButton`; delete the wizard.
6. `CLAUDE.md`.

## Verification

```bash
cd backend  && uv run pytest tests/unit/test_pipeline_matrix.py -x   # fails before task 1
cd backend  && uv run pytest
cd frontend && pnpm vitest run src/lib/compare-matrix.test.ts
cd frontend && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm exec eslint src
```

**End-to-end** (regex only — no keys, no spend; the stack is already up from
the worktree):

1. Open an eval pipeline. The **Comparison matrix** panel is present, above
   the steps; a transform pipeline does not show it.
2. Tick two providers. The cell count updates live. `regex` is disabled and
   names the fields lacking a `pattern`; a provider with no key is disabled
   and names its env var.
3. Save. **Reload the page — the matrix is still there**, chips in the same
   state. This is the assertion the whole plan exists for.
4. `Estimate` → cells, documents, calls, cost. `Run` is disabled until it has
   been seen, and says why.
5. `Compare 3 configs` → three runs → the comparison grid, as today.
6. Edit one axis, save, re-run → the unchanged cells are cached and cost `$0`;
   only the new cell spends.
7. From a transform pipeline: `Compare…` creates the twin and lands on it with
   the panel ready, and a second press does not create a second twin.

## Calls made

- **Persisted matrix, cells still pipelines.** Delivers the ergonomics with no
  migration; the variant cleanup is a separate plan whose risk is real.
- **N=1 stays first-class.** A single-config eval run is the nightly
  regression check — "did my prompt edit make this worse?" — and must not
  become a degenerate comparison.
- **Validate axes at save.** A guard that fires only at spend has already let
  a typo become a priced estimate once.
- **Non-eval pipelines reject a matrix** rather than ignoring it.
- **The wizard is deleted, not left as a second path.** Two places to
  configure one thing is how the eval-set and pipeline surfaces drifted apart
  in the first place.

## Not doing

- Collapsing sweep cells so they stop being pipelines, and the migration of
  existing variants — the obvious next plan.
- Per-field `pattern` as a matrix axis (needs list-index support in
  `apply_cell`).
- Scheduling a comparison; the stored-matrix fallback is the groundwork, the
  UI is not in scope.
