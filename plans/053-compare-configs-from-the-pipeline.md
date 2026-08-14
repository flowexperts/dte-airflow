# Plan 053 — Compare configs from the pipeline you already have

## Context

Plan 051 shipped a working eval harness. Nobody can reach it.

Measured click-path for the most common goal a user actually has — *"I have an
extraction pipeline, I want to know whether claude, openai, or regex does this
better"* — is **28 steps minimum, 35–39 realistically**, and it is **not
completable in the UI**:

- `provider: regex` in a sweep runs against a structure step with no `pattern`
  per field, so that cell scores ~0. The literal three-way comparison is a trap.
- CSV label import needs `doc_key` sha256 values. **No UI anywhere lists them.**
- Field names must be hand-retyped twice — once in the eval set's `field_specs`,
  once in the structure step's `model.fields` — under a warning saying a
  mismatch "won't error; it scores zero on every document."
- An existing transform pipeline **can never be converted to an eval pipeline**;
  the `pipeline_type` control only exists on `/pipelines/new`.
- Consensus bootstrap — the fastest way to get labels — is gated behind building
  *two* eval pipelines by hand first.

The root cause is the **entry point**, not the object model. The UI makes you
start at "eval set", an abstract object you must define from scratch, when you
are in fact starting from a pipeline that already declares the source, the
fields, and the extraction config. Everything the eval set needs is already
sitting in that pipeline.

**Industry standard confirms the shape.** Braintrust, LangSmith, Humanloop and
Phoenix all open label-free: run N configs, show outputs side by side with cost
and latency. Labels are curated *from runs you already reviewed*, never
collected upfront. Reference-free scoring (LLM judge) covers the gap. DTE
already has every one of these primitives — inspector accept/fix, `consensus()`,
`POST /eval-sets/{id}/propose` — they are simply not on any path a user walks.

**Intended outcome:** four steps from a pipeline to a provider comparison, with
zero labels required, and one further click to turn that comparison into scores.

Target path:

```
/pipelines/{id} → "Compare…" → tick claude/openai/regex → Estimate → Launch
                              → comparison grid (agreement, cost, latency)
                              → [optional] "Accept 41 agreed as labels" → F1 ranking
```

Everything else — the eval set, the eval-pipeline twin, the field specs, the
doc_keys — is derived. The user never types a field name twice.

## Design

### The label-free comparison is the product

The current leaderboard's empty state is *"No comparable runs yet."* That is the
wrong default. A sweep with no labels still answers most of the question:

- **Where do the providers disagree?** Uses the eval set's own comparators via
  the existing `_values_agree` (`dte/evals/bootstrap.py`) — so `$1,240.50` and
  `1240.50` count as agreement, not a difference.
- **What did each cost, and how slow was it?** `throughput_stats`
  (`dte/evals/cost.py`) already records this per run.
- **How often did each abstain?** `null_rate` is already computed.

Scores are an *addition* to that view when labels exist, not a precondition for
it. The disagreement set is simultaneously the review queue — which is exactly
what `consensus()` was built for.

### Nothing new is invented backend-side

Every piece of machinery exists. The work is derivation and assembly:

| Need | Already exists |
|---|---|
| Expand a matrix into runs | `_expand_matrix` + `apply_cell` (`dte/evals/sweep.py`) |
| Deterministic variant ids so re-runs hit cache | `variant_id` (`sweep.py:97`) |
| Agreement under tolerance | `_values_agree` / `consensus` (`bootstrap.py`) |
| Cost, latency, cache-hit per cell | `throughput_stats` (`cost.py:84`) |
| Scores + Wilson ties when labels land | `join_and_score`, `_rank_with_ties` |
| Write agreed labels | `POST /eval-sets/{id}/bootstrap` (`evals.py:438`) |

## Backend

### 1. Derivation — `backend/dte/evals/derive.py` (new)

```python
def field_specs_from_structure(step: dict) -> list[dict]
def eval_set_fingerprint(source_id: str, specs: list[dict]) -> str
```

Maps `model.fields[]` → `field_specs[]`. The type map is the whole content, and
it is mechanical (structure types are a strict subset of comparator types):

| structure `type` | eval `type` | note |
|---|---|---|
| `int`, `float` | `numeric` | carries `comparator: {rel_tol: 0.0}`; formatting-forgiving by default |
| `date`, `timestamp` | same | |
| `string` | `string` | |
| `boolean` | `boolean` | |

`description` carries across. `pattern`, `required`, `examples` do not — they
steer extraction, not scoring. **`llm_judge` is never derived** — it costs money
and flatters same-family extractors; it stays an explicit opt-in.

`eval_set_fingerprint` makes derivation idempotent: same source + same field set
returns the existing eval set rather than accumulating a new one per click.

### 2. `POST /api/pipelines/{id}/as-eval` — the eval twin

`dte/api/routes/pipelines.py`. Copies steps verbatim via the existing
`detached_copy` (`sweep.py:43`), sets `pipeline_type="eval"`, drops `output_id`,
id `f"{id}__eval"`. **Idempotent** — returns the existing twin if present. This
is the exact mirror of `POST /eval-sets/{id}/promote` (`evals.py:816`), which
already goes eval → transform; write it in the same shape.

Also **normalises sweepable keys** on the twin's structure step: writes
`params.model` explicitly with the provider's current default. `apply_cell`
refuses to create a leaf that doesn't already exist (`sweep.py:89`) — a guard
worth keeping, since it is what stops a typo becoming N identical cells. Filling
the keys on the twin is the right side to fix.

### 3. `POST /api/eval-sets:for-pipeline` — derive the set

Body `{pipeline_id}`. Resolves the documents source from `pipeline.sources`,
derives `field_specs` via `derive.py`, returns the existing set on fingerprint
match or creates one. 422 with the existing message if no documents source.

### 4. `GET /api/sweeps/{sweep_id}/comparison` — the label-free payload

The one genuinely new endpoint.

```
{ cells: [{pipeline_id, run_id, cell, status,
           cost_usd, latency_p95_ms, cache_hit_rate, null_rate,
           macro_f1?, macro_f1_interval?, n?, rank?, tied_with_leader?}],
  fields: [{name, agreement_rate, disagreement_count}],
  documents: [{doc_key, doc_ref, values: {cell_id: {field: value}}, agrees: bool}],
  labels: {total, agreed_unlabeled} }
```

Score fields are present only when labels exist — absent is the normal case, not
an error. Reuses `_best_and_last`, `_rank_with_ties`, `throughput_stats` and
`_values_agree` unchanged.

### 5. Three fixes this flow makes load-bearing

- **OpenAI prices in `cost.py`.** `PRICES` has no `gpt-*` entry, and one
  unpriced row nulls the whole total by design (`cost.py:114`). "Which provider
  is cheapest" is the headline metric of this flow and it currently reads
  `unknown` the moment openai is in the matrix. Add the gpt-5 family; keep the
  existing "unknown is None, never a guess" rule for everything else.
- **`eval_max_sweep_cells` is inert.** `evals.py:748` reads it via `getattr`
  off `Settings`, which has no such field and `extra="ignore"` — so
  `DTE_EVAL_MAX_SWEEP_CELLS`, named in the error message at `:754`, does
  nothing and the cap is always the hard-coded 50. Declare it on `Settings`
  (`dte/config.py`).
- **The sweep route skips trigger-route validation.** `start_eval_run`
  (`pipelines.py:796`) bypasses the corpus-match, engine-compat and shared-fs
  guards that `POST /{id}/trigger` runs. Tolerable while sweep was a side door;
  not tolerable once it is the primary path. Extract those checks into a helper
  and call it from both.

## Frontend

### Entry — `components/pipeline/compare-button.tsx` (new)

On `/pipelines/{id}`, beside Trigger. Rendered when the pipeline has a
`structure` step, for both `transform` and `eval` types. Gated on
`can("eval:write")`.

### Wizard — `components/evals/compare-wizard.tsx` (new)

One panel, no page navigation. Replaces `sweep-launcher.tsx`'s free-text
axis/values inputs (whose help text contradicts itself — the docstring promises
a cartesian product, the form offers one axis).

- **Provider** row: checkboxes `claude` / `openai` / `regex`, first two ticked.
- `regex` is **disabled with an inline reason** when any field lacks a `pattern`:
  *"regex needs a pattern per field — 2 of 3 have none. Add them on the
  structure step first."* This closes the trap that currently makes the
  three-way comparison silently score zero.
- **Model** row (optional): checkboxes from `cost.PRICES`, filtered to the
  ticked providers.
- **Instructions** row (optional): 2–3 textareas for prompt variants.
- Multi-row selection builds the cartesian matrix — the shape the API has always
  accepted.
- Live cell count → **Estimate** → **Launch**, keeping the existing rule that
  Launch is unreachable until an estimate has been seen.

Matrix construction goes in `lib/compare-matrix.ts` as a pure function so it is
unit-testable without rendering.

### Comparison grid — `app/(app)/pipelines/[id]/compare/page.tsx` (new)

`?sweep=<id>`, client component, SWR-polled until every cell is terminal.

1. **Cell header cards** — one per config. Cost, p95 latency, cache-hit,
   null-rate. F1 with `ScoreBar` and the tie badge *only when labels exist*.
2. **Field agreement** — one row per field, agreement rate rendered with the
   existing `toneVar` idiom.
3. **Document table** — one row per document, one column per cell.
   Disagreeing cells toned; row click opens the existing inspector modal
   (`InspectRowButton`).
4. **Label affordance** — `Accept {n} agreed as labels`, calling the existing
   `POST /eval-sets/{id}/bootstrap` with `confirm: true`. Carries the existing
   same-provider warning verbatim. After it succeeds, scores appear in the
   header cards on the next poll.

The empty/no-labels state says *what you can already see*, not what is missing.

### Kept as-is

`/eval-sets` and its tabs stay. Someone who wants to build a corpus first is
still served; they are simply no longer the only person served. The
`run-eval-button` empty state gets a link to the Compare flow instead of
instructions to hand-build a pipeline with `pipeline_type: eval`.

## Files

**New backend:** `dte/evals/derive.py`,
`tests/unit/test_derive.py`, `tests/unit/test_comparison_payload.py`,
`tests/scenarios/test_compare_flow.py`

**Modified backend:** `dte/api/routes/pipelines.py` (`as-eval`, shared trigger
validation), `dte/api/routes/evals.py` (`:for-pipeline`, `/sweeps/{id}/comparison`),
`dte/evals/cost.py` (openai prices), `dte/config.py` (`eval_max_sweep_cells`)

**New frontend:** `components/pipeline/compare-button.tsx`,
`components/evals/compare-wizard.tsx`, `lib/compare-matrix.ts`,
`lib/compare-matrix.test.ts`, `app/(app)/pipelines/[id]/compare/page.tsx`,
`components/evals/comparison-grid.tsx`

**Modified frontend:** `lib/api.ts` (+ `pnpm gen:types`),
`components/pipeline/rail.tsx`, `components/evals/run-eval-button.tsx`

**Deleted:** `components/evals/sweep-launcher.tsx` — superseded by the wizard.

## Tasks

Worktree per CLAUDE.md: `git worktree add ./worktrees/053-compare -b feature/053-compare`.
TDD throughout — failing tests first.

1. `derive.py` + unit tests. Type map, fingerprint idempotence, `llm_judge`
   never derived, `pattern`/`required` not carried across.
2. `POST /pipelines/{id}/as-eval` + idempotence test + `params.model`
   normalisation test (proves a `params.model` sweep no longer 422s).
3. `POST /eval-sets:for-pipeline` + test that a second call returns the same id.
4. `GET /sweeps/{id}/comparison` + unit test on assembly, both with and
   without labels present.
5. The three fixes: openai prices, `eval_max_sweep_cells` on `Settings`, shared
   trigger validation. Each with a test that fails first.
6. `pnpm gen:types`; `lib/compare-matrix.ts` + vitest (cartesian expansion,
   regex gating when patterns are absent, cell count).
7. Wizard + Compare button.
8. Comparison grid; delete `sweep-launcher.tsx`, relink `run-eval-button`.
9. Scenario test `test_compare_flow.py` with the regex provider end-to-end —
   hermetic, no API keys, no spend.
10. Update `CLAUDE.md`: the Compare flow as the documented entry point.

## Verification

```bash
cd backend && uv run pytest tests/unit/test_derive.py -x     # first, fails before step 1
cd backend && uv run pytest                                  # default suite stays green
cd backend && uv run pytest tests/scenarios -m scenario -k compare -v
cd frontend && pnpm vitest run src/lib/compare-matrix.test.ts
cd frontend && pnpm exec next typegen && pnpm exec tsc --noEmit
```

**End-to-end acceptance** (stack up, demo data seeded, `regex` only — no keys,
no spend):

1. Open a transform pipeline with a `structure` step. **Compare…** is present.
2. Tick `claude` + `openai`. `regex` is disabled and states which fields lack a
   pattern — not silently offered.
3. Estimate shows cells / documents / calls / cost. Cancel enqueues nothing.
4. Launch. The eval twin and eval set are created without a single field name
   being typed. Confirm `field_specs` match the structure step exactly.
5. The comparison grid renders with **zero labels** — agreement per field, cost,
   latency, per-document values. No error state, no empty state.
6. Click a disagreeing row → inspector opens on the right document.
7. **Accept N agreed as labels** → F1 appears in the header cards; two close
   configs render as tied, not ranked.
8. Re-run the identical sweep → **$0, all cached, identical scores.** A score
   that moves on a cached re-run means scoring is not deterministic and the
   whole comparison is untrustworthy — this is the assertion that matters most.
9. Count the clicks from step 1 to step 5. Target ≤ 5.

## Calls made

- **Label-free is the default view, not a degraded one.** Requiring ground truth
  before showing anything is what left the harness empty. Matches how every
  comparable platform onboards.
- **The eval twin is a real, visible pipeline**, not a hidden variant. It shows
  up under Pipelines → Eval, and Promote already exists to send a winner back.
  A hidden object that runs and bills is worse than one extra row in a list.
- **Derivation is one-directional** — structure step → eval set, never back.
  Two-way sync between two similar-but-unequal field shapes is a source of
  silent drift; the pipeline stays the single definition of what is extracted.
- **`apply_cell` stays strict.** Its guard is what prevents a typo'd axis from
  becoming N identical cells that look like "this setting makes no difference".
  The twin is normalised instead.
- **Not doing:** per-field `pattern` as a sweep axis (needs list-index support
  in `apply_cell` — real, but separate); label editing; a schedules UI;
  holdout-split authoring. All still API-only after this plan.
