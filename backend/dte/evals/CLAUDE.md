### Eval harness (plan 051)

**Scoring core.** `dte/evals/` — `comparators.py` and `scoring.py`. Pure
functions, no I/O, no storage. Comparators are forgiving on formatting and
strict on semantics (`$1,240.50` matches `1240.5`; `1240.50` does not match
`1204.50`). Metrics are precision/recall/F1, never accuracy, and correct
abstention (`tn`) is counted separately from a silent miss (`fn`) — without
that split an extractor that answers nothing scores well.

**Storage** (migration `034`). `eval_sets` holds a labeled corpus for one
extraction task; `eval_examples` holds one labeled document per row. Models in
`dte/models/eval.py`, stores in `dte/store/postgres.py`, protocols in
`store/base.py`, fakes in `tests/fakes.py`.

- **`doc_key` is `sha256(document bytes)`** — the same key the plan-050
  artifact store uses. Labels therefore survive renames and directory moves,
  and join directly against extraction output with no path matching. The model
  rejects anything that isn't a 64-char hex digest: a filename here would join
  against nothing and the set would score a permanent zero with no error.
- **`eval_examples` is upserted on `(eval_set_id, doc_key)`, not on `id`.**
  The natural identity of a label is the document it labels; without the
  UNIQUE constraint, relabeling appends a contradictory second row that then
  gets scored twice.
- **`labels_version` is owned by `bump_labels_version`, never by `save`.**
  Every label write bumps it and runs pin what they scored against, so folding
  it into `save` would let a rename invalidate every historical score. The
  Postgres increment happens in SQL — two concurrent labelers must not both
  read 3 and both write 4.
- **`field_specs` is the scorer's own model.** `EvalSetBase.to_field_specs()`
  is the single conversion, and an unknown comparator type is rejected at save
  time — a bad comparator must fail when the set is created, not at the end of
  a paid sweep.
- **Five new `runs` columns**: `eval_set_id`, `labels_version`,
  `config_digest`, `sweep_id`, `scores`. All nullable with no default —
  "never scored" must stay distinguishable from "scored zero". `runs` is raw
  SQL with no SQLModel, so the select list now lives in one constant
  (`_RUN_COLUMNS`) and the jsonb write set in another (`_RUN_JSONB_COLUMNS`);
  adding a column means editing those two plus the migration. It used to be
  duplicated across `get` and `list_for_pipeline`, where a column added to one
  and forgotten in the other simply vanished from that read path.
- `eval:read` / `eval:write` / `eval:delete` are granted to the seeded roles
  by migration `034` itself. Adding a value to `Permission` in code only
  changes what *may* be checked; the `roles` table holds what is granted.

**The run path.** `pipeline_type: "eval"` pipelines go through the eval branch
of `_run_body`: compile → materialise → join to labels on `doc_key` → score →
persist. Scoring lives in the runner, not the compiler, mirroring
`evaluate_contracts` — precision/recall over a corpus *is* an aggregation, and
`_validate_steps` rejects `aggregate` outside transform pipelines.

- **`artifact_ref` is `artifact://<sha256>`, `doc_key` is the bare digest.**
  `_doc_key_from_ref` strips the scheme. Without it every join misses, the
  corpus scores a flat zero, and nothing errors.
- **`FieldMetrics.f1` is `2tp/(2tp+fp+fn)`**, not the harmonic mean of
  precision and recall. Precision is undefined when an extractor answers
  nothing, so the harmonic form returned `None` for a total failure — which
  renders as "unrated" and drops out of ranking exactly like an unscored set.
- Eval and quality pipelines both have **no destination**. Anything gating on
  `output_id` (the builder's save validation, its schema-inference effect)
  needs to allow both or an eval pipeline cannot be saved or edited.

**Labeling** — four paths, all writing through `EvalExampleStore.save`, all
bumping `labels_version`:

- `POST /eval-sets/{id}/examples:import` (CSV/JSONL), `.../bootstrap`
  (consensus over N variants), `.../propose` (LLM judge), and the
  **inspector's Correct / Fix buttons**, which are the highest-leverage path
  because the reviewer is already comparing the value to the page.
- **`consensus()` requires unanimity, uses the eval set's own comparators, and
  refuses to treat unanimous null as agreement.** All three matter: majority
  voting among variants sharing a model counts one opinion twice; string
  equality would route a currency corpus into review; and a null label asserts
  the right answer is *nothing*, after which every abstaining extractor scores
  a hit. The review UI must agree with this — a variant's miss is never
  offered as a pickable label, and "document doesn't state this" is a separate,
  explicit option.
- Variants sharing a `provider` block auto-accept (409). Judge labels are
  permanently tagged; the leaderboard's >50% warning depends on the tag.

**Sweeps.** `POST /eval-sets/{id}/sweep` with `confirm=false` estimates and
enqueues nothing. Confirmed, each cell becomes a **real pipeline and run** via
`start_eval_run` — the same path a manual trigger uses. `dte/evals/sweep.py`:

- `detached_copy` rebuilds from `model_dump()` rather than `copy.deepcopy`. A
  pipeline loaded from Postgres is SQLAlchemy-instrumented; deep-copying it
  and assigning `.id` raises `ObjectDereferencedError`. The fakes return
  detached instances, so this passes every unit test and 500s in production.
- `variant_id` is derived from the config digest, so relaunching a sweep
  reuses rows and hits the extract cache instead of re-paying under a new name.
- An unknown matrix axis **raises**. Dropping a typo silently yields N
  identical cells scoring the same, which reads as "this setting makes no
  difference".

**A pipeline's schedule** (`pipeline.schedule`, plan 068) carries an optional
`eval_set_id`; the DAG factory hands it to the operator. Validation at save time
repeats the trigger route's rules exactly — a schedule is a trigger on a timer,
and a disagreement between the two surfaces at 2am. No FK: deleting an eval set
a schedule references returns 409 naming the pipelines.

**Frontend** — `/eval-sets` (list, with best-F1 and last-run), `/eval-sets/new`
(create) and `/eval-sets/[id]` (Leaderboard / Examples / Review).
`pipeline_type` includes `"eval"` in `api.ts`, the builder, and `StepsPanel`
(which hides `aggregate`/`pivot` — they would collapse the rows the labels
join against). `/eval-sets` is a **server component**: never
`toLocaleDateString()` there, it hydration-mismatches.

**Three objects, and "eval" used to name two of them.** An **eval set** is the
labeled corpus (`/eval-sets`); an **eval pipeline** is an extraction config
under test (`/pipelines?type=eval`); an **eval run** is one scoring of one
pipeline against one set at one `labels_version`. The route was `/evals` while
the nav also carried "Eval" for pipelines — two different objects a letter
apart. The frontend route now matches the model, the table and the API, all of
which were already `eval_set(s)`; `next.config.ts` keeps a permanent redirect
from `/evals/*`.

Anything user-visible that filters by `pipeline_type` must come from
`PIPELINE_TYPE_TABS` (`lib/pipeline-type.ts`), which drives the sidebar and
the list page together. Eval pipelines shipped creatable and reachable from
nowhere because the nav and the page each knew about a different subset of
types, and an unrecognised `?type=` silently means "no filter".

### Compare: the entry point to the harness (plan 053)

**Start from the pipeline, not the eval set.** Reaching a provider
comparison through plan 051's surfaces took 28 steps minimum and could not
be completed in the UI at all. The object model was fine; the entry point
was wrong. `/eval-sets/new` asked users to declare a source and retype a
field list their pipeline already carried — so `CompareButton` on
`/pipelines/{id}` derives all of it:

```
POST /pipelines/{id}/as-eval          → the eval twin (idempotent)
POST /eval-sets:for-pipeline          → the eval set   (idempotent)
POST /eval-sets/{id}/sweep            → estimate, then confirm
GET  /sweeps/{id}/comparison          → the side-by-side view
```

- **`dte/evals/derive.py` maps `model.fields` → `field_specs`.** One-way
  only. The two shapes are close but unequal (`comparator` on one side,
  `pattern`/`required`/`examples` on the other) and a two-way sync between
  them is how the drift the derivation removes would return.
- **The eval-set id carries a fingerprint** of field names, comparator
  types and comparator options — *not* order and *not* descriptions.
  Reordering fields and rewording a prompt hint are the edits people make
  constantly while iterating; minting a fresh set for either would discard
  every label collected so far. Two pipelines extracting the same fields
  from the same corpus therefore share one set, which is what lets claude
  and openai appear on one leaderboard.
- **The twin normalises sweepable keys** (`params.model`,
  `model.instructions`). `apply_cell` refuses to *create* a leaf that does
  not exist, and that guard is what stops a typo'd axis becoming N
  identical cells reading as "this setting makes no difference" — so the
  twin is filled in rather than the guard loosened.

**The comparison renders with no labels, and that is the point.** The
leaderboard's "No comparable runs yet" is a demand for work nobody has
done, and it is why the harness sat empty. `build_comparison`
(`dte/evals/comparison.py`) answers what needs no ground truth: per-field
agreement, cost, p95 latency, null rate, per-document values. Scores are
added when labels exist; **absent is the normal case, never an error, and
never rendered as zero**.

- Agreement rules are **imported from `bootstrap.py`**, not reimplemented —
  comparators not equality, null is not agreement, union not intersection.
  A comparison measuring agreement differently from the thing that writes
  labels would offer "accept 41 agreed" for a number the accept step
  refuses.
- `labels.auto_accept` reproduces bootstrap's shared-provider rule *in the
  payload*, because the UI must know before it offers the button. Sweeping
  models or prompts holds the provider fixed, so the 409 is the common
  case, and a primary button that fails on click is worse than a disabled
  one that explains.
- Rows are **re-materialised, not persisted** — an eval run writes no
  output. Affordable only because plan 050 caches by content hash; opening
  the page parses no PDF and calls no model.

> The leaderboard, comparison grid, review panel and promote UI described below were
> unrouted by plan 067 and deleted in plan 091 (`git log -- frontend/src/components/evals`).

**Shipping the winner is on the comparison, not only the leaderboard**
(plan 054). `promote` used to be rendered solely on the leaderboard, which
ranks *scored* runs — so the page that works without labels had no exit,
and the documented route out (accept labels → leaderboard → promote) is
refused outright whenever every config shares a provider, which is what a
model or prompt sweep produces. `PromoteFromComparison` puts one
`Ship a config…` in the summary bar and chooses the config inside the form.

- **One control, not one per cell.** The promote form does not fit a 220px
  card, and Promote is the page's exit rather than a property of a cell —
  by the time it is reached the decision is made.
- **Nothing is preselected.** Unlabelled, the page computes no ranking;
  labelled, it computes ties rather than winners. A default would assert
  what neither state supports.
- **Unshippable cells stay in the list with the reason attached**
  (`lib/comparison-shippable.ts`). The one that matters: a run whose every
  call failed is `completed` and green, because `on_error: null` fills
  nulls rather than failing — shipping it ships empty columns. A missing
  option reads as a bug; "every row errored" is the useful thing to say.
- `PromoteForm` is shared with the leaderboard. Two implementations would
  drift, and the drift is invisible until a promoted pipeline stops
  matching the digest that was measured.

**The matrix is a property of the eval pipeline** (plan 055, migration
`036`). `Pipeline.matrix` is a nullable JSONB map of dotted axis path →
values to vary, and it saves with the pipeline. The Compare wizard is
**deleted** — its matrix was transient, so a comparison could not be
reopened, adjusted and re-run: you started from an empty form and minted a
fresh set of variant pipelines each time.

- **`MatrixPanel` is reached on demand, not shown inline.** It first
  rendered permanently above the steps, on the theory that "an eval run is
  a comparison run" should be visible every time you open the pipeline. In
  practice most visits are to read a step or check how the last run scored,
  not to launch a new comparison — a block that is 90% of the time inert
  crowds the thing people actually came to look at. `CompareDialog`
  (`components/evals/compare-dialog.tsx`) now hosts the same `MatrixPanel`,
  unmodified, inside a modal opened by the **Compare…** button in the page's
  action row (`CompareButton`, next to Save/Trigger) — the same button a
  transform pipeline uses to derive its eval twin. Edits still flow through
  the pipeline's own `onChange`/Save; the modal has no second dirty state.
- **The structure step's Provider dropdown is unconditional again.** An
  earlier version hid it on eval pipelines on the theory that the matrix
  was the only thing that set provider. That was wrong for the common case
  the matrix explicitly stays out of the way of: an unticked matrix (N=1,
  "the nightly regression check") runs the step's own raw config directly —
  and so does a **schedule**, which calls the same trigger path and never
  reads `pipeline.matrix` at all. Hiding the dropdown left that case with no
  way to choose a provider.
- **Absent means N=1**, not zero: the config as it stands, run once. That
  is the nightly regression check, and `_expand_matrix` returning `[]` for
  an empty product is turned into one cell *at the sweep route*, so its
  other callers are unaffected.
- **A matrix on a non-eval pipeline is a 422**, and so is an axis nothing
  reads. `validate_matrix_axes` (`dte/evals/sweep.py`) is the same rule
  `apply_cell` enforces, hoisted so it also fires at save — it used to fire
  only at spend, after a typo had been estimated and priced.
- **The sweep body still wins when present**; the stored matrix is the
  fallback. Estimate and confirm must price exactly what is on screen,
  including unsaved edits, while a caller with no body (the scheduler) gets
  the pipeline's own comparison — though see above: a schedule fires a
  plain trigger, not a sweep, so today it always gets N=1 regardless of
  what the matrix holds. Making a schedule actually run the matrix is not
  done.
- `draftFromMatrix` is the inverse of `buildMatrix` and is what makes the
  matrix storable: without it the panel renders empty over a saved matrix
  and the next save discards every axis. Axes the panel has no control for
  (`params.max_tokens`) are reported and preserved, never silently dropped.

**Sweep cells are still real pipelines.** The variant machinery
(`prune_cells`, `root_pipeline_id`, `variant_name`, `isSweepVariant`)
survives; collapsing cells so they stop being pipelines is the follow-on
plan, and the migration of existing variants and their runs is where its
risk lives.

**`regex` is gated on patterns** (`lib/compare-matrix.ts`). Without a
`pattern` per field the provider returns nothing on every row and the cell
scores ~0 — which reads as "regex is bad at this" rather than "regex was
never configured". The chip is disabled and names the fields that lack one.

Also fixed here, all three previously invisible: OpenAI models were
unpriced (and one unpriced row nulls a whole run's cost by design);
`eval_max_sweep_cells` was read off a `Settings` that never declared it, so
`DTE_EVAL_MAX_SWEEP_CELLS` was inert; and the sweep skipped the
corpus-match check `trigger` enforces — now `validate_eval_corpus_match`,
called by both, before the estimate rather than at confirm.

