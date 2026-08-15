# Plan 054 — Ship the config that won

## Problem

Plan 053 made the comparison reachable and readable. It does not let you act
on it. A user who has run a comparison, read the grid and decided which
config to keep has, on that page, nothing to click.

The exit exists — `POST /eval-sets/{id}/promote`, which copies a config
verbatim into a transform pipeline so the shipped pipeline keeps the
`config_digest` that was measured. It is rendered in exactly one place:

```
frontend/src/components/evals/leaderboard.tsx:197
    <PromoteButton evalSetId={…} pipelineId={entry.pipeline_id} />
```

The leaderboard ranks **scored** runs, and scores need labels. The comparison
view is deliberately label-free. So the documented path out is:

> accept agreed values as labels → `/eval-sets` → find the set → Leaderboard
> tab → Promote

and that path is **blocked in the common case**: `Accept N agreed as labels`
is refused (409) when every config shares a provider, which is exactly what a
model-or-prompt sweep produces. A user comparing `claude·sonnet-5`,
`claude·haiku-4-5` and `regex` cannot promote from the page where they made
the decision, and cannot reach the page where they could.

This is the same failure plan 053 was written to fix — an object that is
creatable and reachable from nowhere — reintroduced one surface along.

## Design

### One action, not one per cell

The obvious move is a Promote control on each `CellCard`. Rejected, for two
reasons:

- **It does not fit.** `PromoteButton`'s open state renders a `Panel` with a
  two-column input grid and a destination dropdown, inside cards that are
  `min-w-[220px]` in a flex row.
- **It is the wrong shape.** Cell cards report per-cell facts — cost, p95,
  blank rate, agreement. Promote is the page's exit, not a property of a
  cell. N identical buttons on a page that has no opinion about which to
  press asks the user to re-make a decision they have already made, and
  spends the weight of a mutating action on every card.

Instead the existing summary bar — which already carries the disagreement
count and `Accept N agreed as labels` — becomes the single "what now" row:

```
These configs disagree on 3 of 5 documents.   [Accept 2 agreed as labels] [Ship a config…]
```

`Ship a config…` opens one form: **which config** (dropdown, labelled as the
cards are — `regex · $0.0000`), new pipeline id, name, destination.

### No cell is pre-selected, and none is recommended

Without labels there is no computed winner. The leaderboard's Promote hangs
off a rank; here there is no rank, and defaulting the dropdown or badging a
cell would assert a ranking the page did not compute. The user chose regex
because it was free, exact and agreed with both Claude cells — that judgment
is theirs and the UI must not pretend it made it.

When scores *do* exist, the existing `best` / `tied` pills already mark the
leader on the cards. The dropdown still does not default: a leader inside
another cell's confidence interval is not a winner, and the tie pill is
precisely the case where a default would be most wrong.

### Cells that cannot ship are not offered

Excluded from the dropdown, each with the reason shown rather than the option
silently missing:

- `status` is `failed` — the run did not finish.
- `error_count == documents` — every row errored. The run is green (`on_error:
  null` fills nulls rather than failing) but nothing was extracted, and
  shipping it would ship a pipeline that produces empty columns.
- `status` is `pending` / `running` — not finished, nothing to judge.

A comparison where no cell is shippable disables the button and says why.

### Reuse, with the form lifted out of the card

`PromoteButton` keeps its current behaviour on the leaderboard. Extract its
form body into `PromoteForm` (props: `evalSetId`, `pipelineId`, `onDone`) so
both surfaces share one implementation, and the comparison's version wraps it
with the config dropdown that chooses `pipelineId`. The toast on success —
which echoes the config digest, the only real evidence that what shipped is
what was measured — is unchanged.

### Backend

No new endpoints. `promote_pipeline` already validates what matters:
`pipeline_type == "eval"`, a non-empty `output_id`, and a 409 on an id that
already exists. `GET /sweeps/{id}/comparison` already returns `eval_set_id`
and each cell's `pipeline_id`, `status`, `error_count` and `documents` — the
payload needs nothing added.

One backend change, small: promote currently 422s an eval pipeline whose
steps are fine but which is a sweep *variant*, only in the sense that nothing
stops it. That is correct and stays — a variant is a real pipeline and is
exactly what we want to promote.

## Files

**Modified frontend**
- `components/evals/promote-button.tsx` — extract `PromoteForm`; `PromoteButton`
  becomes a thin wrapper over it (leaderboard behaviour unchanged).
- `components/evals/promote-from-comparison.tsx` *(new)* — the config dropdown
  + `PromoteForm`, and the shippability filter.
- `components/evals/comparison-grid.tsx` — `Ship a config…` in the summary bar;
  the bar renders when there are shippable cells even if `agreed_unlabeled` is 0.

**New tests**
- `lib/comparison-shippable.ts` + `.test.ts` — which cells are offered and why,
  as a pure function (vitest, no rendering).

**Modified docs**
- `CLAUDE.md` — the Compare section gains the exit: comparison → promote.

## Tasks

Worktree per CLAUDE.md: `git worktree add ./worktrees/054-ship -b feature/054-ship`.
TDD — the pure function first, failing.

1. `lib/comparison-shippable.ts` + vitest: failed excluded, all-errored
   excluded, running excluded, none-shippable case, and that nothing is
   marked recommended.
2. Extract `PromoteForm` from `PromoteButton`; assert the leaderboard is
   unchanged.
3. `PromoteFromComparison` — dropdown + form + disabled/empty states.
4. Wire into the summary bar; make the bar render on shippable-but-unlabelled
   comparisons.
5. `pnpm exec tsc --noEmit`, `pnpm exec eslint`, `pnpm vitest run`.
6. CLAUDE.md.

## Verification

```bash
cd frontend && pnpm vitest run src/lib/comparison-shippable.test.ts
cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint src
cd backend  && uv run pytest          # unchanged; promote already covered
```

**End-to-end** (regex only — no keys, no spend):

1. Run a comparison from a pipeline with a `structure` step.
2. Summary bar shows `Ship a config…` with no cell pre-selected.
3. A failed or all-errored cell is absent from the dropdown, with the reason
   shown.
4. Promote regex → new transform pipeline exists, with a destination.
5. The toast's digest matches the compared cell's `config_digest`.
6. Open the promoted pipeline: steps identical to the cell's, `output_id` set,
   `pipeline_type: transform`.

## Calls made

- **One action, not per cell.** The decision is already made by the time the
  user reaches for it; the UI's job is to accept it, not to re-offer it N ways.
- **Never a default config.** The page computes no ranking without labels, and
  computes ties rather than winners with them. A pre-selected dropdown would
  assert what neither state supports.
- **Unshippable cells are shown as excluded, not hidden.** A missing option
  reads as a bug; a disabled one with "every row errored" is the most useful
  thing the page can say.

## Not doing

- Promoting into an *existing* pipeline (overwrite semantics, revision
  implications — separate).
- Creating a destination inline from the promote form; you pick an existing
  one, as the leaderboard's promote does today.
- Any change to how promote works server-side.
