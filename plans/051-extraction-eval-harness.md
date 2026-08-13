# Plan 051 — Eval harness for extraction

> Depends on plan 050 Phase 2 (the `structure` op and the document inspector).

## Context

Plan 050 gives users a way to *build* PDF extraction and a 5-document variant
compare to iterate on it. That is enough to get something working and nowhere
near enough to know it works. Disagreement highlighting tells you a prompt is
unstable; it cannot tell you which of two stable prompts is *right*, and it
cannot tell you that last week's config silently got worse when a provider
updated a model.

The ask is a harness where people try multiple things and find out what works
best — on labeled data, with real metrics, comparable over time.

The failure mode to design against is not "the harness is missing features."
It is **an eval system nobody has labels for**. Every team builds the
scoreboard and then discovers hand-labeling 200 PDFs is nobody's Tuesday, and
the harness sits empty. So labeling is treated as the primary problem here, and
four separate paths into ground truth ship in v1.

The second failure mode is **a harness that lies**. Exact string match scores
`$1,240.50` against `1240.50` as wrong; "accuracy" makes an extractor that
abstains 90% of the time look excellent; an n=8 leaderboard showing 94.1% vs
91.7% is noise rendered as a decision. Each of those gets an explicit
countermeasure below.

### What the codebase already gives us

Exploration confirmed most of the machinery exists and should not be rebuilt:

- `enqueue_run` (`dte/worker/tasks.py:253`) — the single atomic "make a run
  happen" entry point (run row + procrastinate job on one connection, with RLS
  tenant config). Eval runs call it; they do not re-implement it.
- `evaluate_contracts(contracts, target, con)` (`dte/quality/evaluator.py`) runs
  *after* the pipeline in the transform branch of `_run_body`. **Scoring is the
  exact structural analogue** and slots in the same place.
- Schedules (`dte/worker/scheduler.py`, croniter + a procrastinate periodic
  tick) are already pipeline-scoped — nightly regression runs are nearly free.
- `runs.quality_checks JSONB` + the `_apply_profile` precedent of carrying a
  numeric metric payload through `QualityResult.detail`.
- Frontend list/detail/tab conventions are rigid and well-established.

### Two findings that shaped the design

**1. Scoring cannot be a quality pipeline.** `PipelineBase._validate_steps`
(`models/pipeline.py:1099`) explicitly rejects `aggregate` and `pivot` when
`pipeline_type == "quality"`. Precision/recall over a corpus *is* an
aggregation. Rather than relax that guard, **scoring runs in the runner, not the
compiler** — mirroring `evaluate_contracts`. This turns out to be better
regardless: no new compiler op, no user-visible "score" step to wire up
correctly, and the compiler stays a pure table→table function.

**2. `LookupTable` is the wrong home for labels.** `mappings: dict[str, str]`
is a flat single-key→single-string map, loaded as one JSONB blob with no
pagination, and delete-guarded against `map`/`lookup` steps. Ground truth is
many fields per document over hundreds of documents, and needs row-level
upsert from the inspector. It gets its own table.

## Architecture

### Entities

**`eval_sets`** — a labeled corpus for one extraction task.

```
id, name, source_id (the documents source), field_specs JSONB,
labels_version INTEGER NOT NULL DEFAULT 1, tenant_id, created_at, updated_at
```

`field_specs` mirrors the `structure` step's data model (name / type /
description) **plus** a per-field `comparator` config — because the task
definition and the scoring definition are the same thing and must not drift.

**`eval_examples`** — one labeled document.

```
id, eval_set_id FK, doc_key TEXT, doc_ref TEXT,
labels JSONB, label_source TEXT, split TEXT DEFAULT 'train',
labels_version INTEGER, tenant_id, created_at, updated_at
UNIQUE (eval_set_id, doc_key)
```

`doc_key = sha256(document bytes)` — **the same key plan 050's artifact store
uses.** This is load-bearing: labels survive file renames and directory moves,
they join directly against extraction output with no path matching, and a
document already in the artifact cache is already keyed correctly.

`label_source ∈ {human, consensus, imported, judge}` — never collapse these.
Knowing a label came from an LLM judge rather than a human is essential when
the scores look suspiciously good.

`split ∈ {train, holdout}` — see "overfitting" below.

**Eval runs reuse the `runs` table.** New columns:
`eval_set_id TEXT`, `labels_version INTEGER`, `config_digest TEXT`,
`sweep_id TEXT`, `scores JSONB`.

⚠️ Three places must be updated together or the columns silently vanish:
the `INSERT`/`SELECT` list in `PostgresRunStore` (`dte/store/postgres.py:121`,
used by both `get` and `list_for_pipeline`), the jsonb-serialisation tuple in
`RunStore.update` (`:161`, currently only `params` and `sql_query`), and the
migration. There is no `Run` SQLModel — `runs` is raw SQL — so the compiler
will not catch a miss.

**No sweep entity.** A sweep is N runs sharing a `sweep_id`. The leaderboard
groups by config regardless, so a table would be a parallel stack for no gain.

**`config_digest`** = `sha256` of the canonicalised `extract` + `structure` step
params. This is what makes drift detectable: same digest + same
`labels_version` + a different score later means *the provider changed under
you*, which is the single most valuable thing a scheduled eval can tell you.

### `pipeline_type: "eval"`

A third value on the existing Literal (`pipeline_type` arrived in migration
026). An eval pipeline is an ordinary documents → `extract` → `structure`
pipeline with no destination, bound to an eval set at trigger time.

Runner flow, in `_run_body` alongside the existing `quality` branch:

```
resolve sources (no destination, same as the quality branch)
  → load labels for (eval_set_id, labels_version) into DuckDB as __labels__
  → compile_pipeline(...) as normal
  → materialise the compiled table
  → JOIN result ⋈ __labels__ ON doc_key
  → score(row_pairs, field_specs) → per-field + corpus metrics
  → r_store.update(run_id, scores=..., config_digest=..., labels_version=...)
  → status: completed | completed_with_warnings (score below threshold) | failed
```

Labels are materialised straight into the run's DuckDB connection — no new
source kind, no `Source` row, no join step for the user to wire.

### Comparators — where evals actually get hard

`backend/dte/evals/comparators.py`:

```python
def compare(expected, actual, field_type: str, opts: dict) -> MatchResult
# MatchResult{matched: bool, score: float, reason: str}
```

| type | behaviour |
|---|---|
| `numeric` | strip currency symbols, thousands separators, whitespace; compare with `abs_tol` / `rel_tol` |
| `date` | parse both to `date` (dateutil), compare normalised; configurable day tolerance |
| `string` | normalise (case, collapse whitespace, strip punctuation) then exact; optional `fuzzy_threshold` on ratio |
| `enum` | exact after case-fold, against the declared value set |
| `list` / `set` | Jaccard overlap, or exact set equality when `strict` |
| `llm_judge` | opt-in only, for free-text fields where exact match is meaningless |

Defaults are deliberately forgiving on formatting and strict on semantics.
`llm_judge` is **never a default** — it has its own bias and its own cost, and a
judge that shares a family with the extractor will flatter it. The UI labels
judge-scored fields distinctly.

### Metrics — precision and recall, not accuracy

Per field, over the corpus, classify each (expected, actual) pair:

```
expected non-null, comparator matched        → tp
expected non-null, actual non-null, no match → fp AND fn   (wrong answer)
expected non-null, actual null               → fn          (silent miss)
expected null,     actual non-null           → fp          (hallucinated)
expected null,     actual null               → tn          (correct abstention)
```

> **Corrected during implementation.** This originally counted a wrong answer
> as a false positive only, which lets an extractor that answers every row
> incorrectly report **perfect recall** — nothing was ever "missed". A wrong
> answer is two failures: an incorrect emission *and* a failure to produce the
> right value. Counting both is also the standard convention in extraction
> evaluation. Every acceptance assertion below still holds under the stricter
> definition. Implemented and tested in `dte/evals/scoring.py`.

Metrics whose denominator is empty return `None`, never `0.0` or `1.0` — an
undefined score must not render as a real one.

→ `precision`, `recall`, `f1`, `exact_match_rate`, `n`, `mean_confidence`,
`null_rate`. Corpus level: **macro-F1** across fields (not micro — a single
easy field should not carry the score), plus cost, latency p50/p95, cache-hit
rate.

Distinguishing correct abstention (`tn`) from a silent miss (`fn`) is the whole
reason not to report accuracy. An extractor that returns null 90% of the time
looks superb on "accuracy over answered rows" and is useless.

### Getting labels — all four paths

1. **Accept / fix from the inspector.** Plan 050's document inspector already
   puts extracted fields beside the rendered page, where a human is already
   verifying. Two buttons: *correct* upserts the row as ground truth as-is;
   *fix* opens the field for the right value. Labeling becomes a byproduct of
   reviewing, with no new surface. `POST /api/eval-sets/{id}/examples`.
2. **Consensus bootstrap.** `POST /api/eval-sets/{id}/bootstrap` runs N cheap
   variants over the corpus; rows where **all** variants agree are written as
   `label_source="consensus"`; disagreements go to a review queue. Typically
   ~80% auto-labeled, leaving a few dozen for human attention — a labeled set in
   an afternoon. This is why disagreement-highlighting exists in 050: the
   disagreement set *is* the review queue.
3. **Import.** `POST /api/eval-sets/{id}/examples:import`, CSV/JSONL keyed by
   filename or `doc_key`. Filenames resolve to `doc_key` by hashing at import.
   The only path that works when labels already exist elsewhere.
4. **LLM-as-judge proposal.** A model proposes labels, human confirms in the
   review queue. Fastest cold start, permanently tagged `label_source="judge"`,
   and the leaderboard warns when a set is >50% judge-labeled — you are
   partially scoring models against a model.

Any label write bumps `eval_sets.labels_version`. Runs pin the version they
scored against.

### Three honesty guardrails, built not documented

- **Sample size.** Compute a Wilson 95% interval on macro-F1. Display `n`
  beside every score. **If the top two intervals overlap, render them as tied**
  with "within noise (n=42)" — do not award a rank-1 badge. A leaderboard that
  declares winners on n=8 is worse than no leaderboard.
- **Label versioning.** Runs scored at an older `labels_version` render greyed
  with "labels changed since this run" and are excluded from ranking. Silent
  invalidation of historical comparisons is how eval systems rot.
- **Overfitting.** `split` marks holdout examples, excluded from the default
  leaderboard and scored in a separate column. A large train/holdout gap means
  the prompt was tuned to the eval set, and it is visible rather than inferred.

### Sweeps

`POST /api/eval-sets/{id}/sweep` takes a config matrix (providers × models ×
prompts × granularity), expands the cartesian product, and calls `enqueue_run`
per cell with a shared `sweep_id`. Pre-flight returns
`{cells, documents, uncached_calls, est_cost_usd}` and **requires explicit
confirmation** before enqueueing.

The 050 extract/structure split earns its keep here more than anywhere: PDF
parsing is cached by content hash, so a 5×3 sweep over 200 documents pays for
parsing once and only the 3,000 structure calls vary — and re-running the same
cell is free.

`DTE_EVAL_MAX_SWEEP_CELLS` (default 50) is a hard stop.

### Scheduled regression

Attach an existing `Schedule` to an eval pipeline — no new scheduling code.
The nightly run produces a new eval run with the *same* `config_digest`; the
runner compares against the previous run at that digest and emits a
`completed_with_warnings` status when macro-F1 drops more than
`regression_threshold` (default 3pp, and only when the drop clears the Wilson
interval, so noise does not page anyone).

## Frontend

Follows the established list/detail conventions exactly — see
`src/app/(app)/connections/page.tsx` as the canonical list page (`revalidate =
30`, try/catch → `humanizeError` → `InlineError`, `Topbar` crumbs from
`{label: "Workspace", href: "/"}`, `PageHeader` with `sub={n total}` + `lede`,
body `<div className="px-14 py-8">`, a separate `"use client"` table receiving
`rows`).

**`/evals`** — server page + `EvalSetsTable` client component. Columns: name,
documents, labeled %, best macro-F1, last run.

**`/evals/[id]`** — tabs wired exactly like `components/pipeline/canvas.tsx`:
`sticky top-[52px] z-10`, `Tabs` primitive, `history.replaceState` for
query-string addressability, default tab drops the param.

- **Leaderboard** — `DataTable` of eval runs. Config column (provider/model/
  prompt label), macro-F1 rendered with the progress-bar idiom from
  `QualityCheckRow` (`components/run/quality-panel.tsx`), per-field F1 chips
  toned via `toneVar` (`components/run/helpers.ts`), `n`, holdout column, cost,
  p95 latency, date. Headline aggregates use `Metric`/`MetricRow`. Ties inside
  the interval render as ties. Row actions: *Promote to pipeline*, *Re-run*.
- **Examples** — paged `DataTable` (`Pagination` inside the `Panel`, per
  `components/pipeline/activity.tsx`) of labeled documents; row click opens the
  050 document inspector with labels displayed alongside extraction.
- **Review** — the disagreement / unlabeled queue. Inspector + accept/fix,
  keyboard-driven (`j`/`k`/`enter`) because this is a volume task.

**Per-field drill-down** — clicking a field's F1 lists its failing examples;
each row shows expected vs actual in the two-column red-strike / green idiom
from `builder/history/DiffView.tsx`. Note `DiffView` is bound to `PipelineDiff`
and its own SWR call — write a sibling in the same visual idiom rather than
trying to parameterise it.

**Promote to pipeline** closes the loop: take the winning config and create or
update a real transform pipeline with those `extract` + `structure` steps.

Sidebar: an `<NavGroup>` + `<NavItem href="/evals">` after the Pipelines block
in `app-sidebar.tsx`, gated on `can("eval:read")`.

## Task list

Worktrees per CLAUDE.md: `git worktree add ./worktrees/<name> -b feature/<name>`.

### Phase 1 — storage + scoring core (`feature/051-eval-core`)
1. Alembic `034` (head is `033`): `eval_sets`, `eval_examples`, and the five new
   `runs` columns. Follow the `032_schedules` tenant pattern — `tenant_id NOT
   NULL DEFAULT 'default'`, `ENABLE`+`FORCE ROW LEVEL SECURITY`,
   `tenant_isolation` policy. Add `eval:read`/`eval:write` perms alongside 012's RBAC.
2. `EvalSetBase`/`EvalSet`, `EvalExampleBase`/`EvalExample` in
   `dte/models/eval.py` following the two-class SQLModel pattern from CLAUDE.md.
3. `EvalSetStore`/`EvalExampleStore` protocols in `store/base.py` + Postgres
   impls (three-verb template) + fakes in `tests/fakes.py`.
4. `PostgresRunStore`: new columns in the select list **and** the `update`
   jsonb tuple. Add `list_for_eval_set(eval_set_id, ...)`.
5. `dte/evals/comparators.py` + `dte/evals/scoring.py` (tp/fp/fn/tn → P/R/F1,
   macro-F1, Wilson interval). **Unit tests first** — this is pure, fast, and
   the highest-value test surface in the plan. Table-driven cases for currency,
   thousands separators, date formats, null-vs-miss, unicode whitespace.

### Phase 2 — the eval run path (`feature/051-eval-runs`)
6. `pipeline_type: "eval"` Literal + `_validate_steps` allowances.
7. `_run_body` eval branch: materialise labels, join on `doc_key`, score,
   persist. Reuse `enqueue_run`.
8. `config_digest` computation + regression comparison against the prior run at
   the same digest.
9. API: `dte/api/routes/evals.py` — eval-set CRUD, examples CRUD + import,
   `POST /{id}/sweep` (+ pre-flight estimate), `GET /{id}/leaderboard`,
   `GET /{id}/fields/{field}/failures`.
10. Scenario tests with the 050 stub provider — hermetic, no live calls.

### Phase 3 — labeling paths (`feature/051-labeling`)
11. Inspector accept/fix → `POST /eval-sets/{id}/examples`; `labels_version` bump.
12. Consensus bootstrap endpoint + review queue population.
13. CSV/JSONL import with filename→`doc_key` hashing.
14. LLM-judge proposal path, permanently tagged; >50% judge-labeled warning.

### Phase 4 — surfaces (`feature/051-eval-ui`)
15. `pnpm gen:types`; api.ts helpers; sidebar entry.
16. `/evals` list + `/evals/[id]` tab shell.
17. Leaderboard with tie-within-noise rendering, holdout column, per-field drill-down.
18. Examples + Review tabs; keyboard-driven review.
19. Sweep launcher with cost pre-flight confirmation.
20. Promote-to-pipeline.

### Phase 5 — regression (`feature/051-eval-regression`)
21. Attach schedules to eval pipelines; threshold + Wilson-gated alerting;
    drift surfacing on the leaderboard.

## Files touched

**New**: `backend/dte/models/eval.py`, `backend/dte/evals/{__init__,comparators,scoring,bootstrap}.py`,
`backend/dte/api/routes/evals.py`, `backend/alembic/versions/034_evals.py`,
`backend/tests/unit/test_comparators.py`, `test_scoring.py`,
`backend/tests/scenarios/test_eval_run.py`,
`frontend/src/app/(app)/evals/{page.tsx,[id]/page.tsx}`,
`frontend/src/components/evals/*` (table, leaderboard, examples, review, sweep launcher).

**Modified**: `backend/dte/models/pipeline.py` (`pipeline_type` Literal,
`_validate_steps`), `backend/dte/store/{base,postgres}.py` (two new stores +
`runs` columns in the select list and the `update` jsonb tuple),
`backend/dte/api/routes/pipelines.py` (`_run_body` eval branch),
`backend/dte/api/{main,deps}.py`, `backend/tests/fakes.py`,
`frontend/src/lib/{api.ts,api-types.ts}`,
`frontend/src/components/app-sidebar.tsx`,
`frontend/src/components/document-inspector/*` (accept/fix buttons),
`plans/050-unstructured-extract-and-structure.md` (Part A), `CLAUDE.md`.

**Deleted**: none.

## Verification

```bash
# Comparators + scoring — pure, fast, run constantly
cd backend && uv run pytest tests/unit/test_comparators.py tests/unit/test_scoring.py -x

# Default suite stays green
cd backend && uv run pytest

# Eval run end to end, stub provider
cd backend && uv run pytest tests/scenarios -m scenario -k eval -v

# Postgres-backed store tests
cd backend && DATABASE_URL=... uv run pytest tests/integration -m integration
```

Targeted unit assertions that must exist (these are the lies the harness would
otherwise tell):
- `$1,240.50` vs `1240.5` → match; `1240.50` vs `1204.50` → no match.
- `2024-03-01` vs `01/03/2024` vs `March 1, 2024` → all match under `date`.
- expected `null` + actual `null` → `tn`, **not** counted in precision.
- expected `"x"` + actual `null` → `fn`; expected `null` + actual `"x"` → `fp`.
- an extractor answering 1 of 10 rows correctly and abstaining on 9 scores
  recall ≈ 0.1, **not** accuracy 1.0.

End-to-end acceptance run:
1. Create an eval set over 20 invoice PDFs with a 3-field spec.
2. Bootstrap with 3 variants → most rows auto-labeled `consensus`, the rest land
   in Review. Label those via the inspector. `labels_version` = 2.
3. Import 5 more labels from CSV; confirm filename→`doc_key` resolution.
4. Launch a 2×2 sweep. Pre-flight shows cell count, document count, and cost;
   **cancelling enqueues nothing**.
5. Leaderboard ranks 4 runs, each with `n`. Confirm two close configs render as
   tied rather than ranked.
6. Drill into a field's F1 → failing examples list → inspector shows expected vs
   actual against the PDF page.
7. Edit one label → all prior runs grey out as "labels changed" and drop out of
   ranking.
8. Re-run the winning cell → **cost $0, all cached, identical score.** If the
   score moves on a cached re-run, scoring is not deterministic and the harness
   is not trustworthy — this is the assertion that matters most.
9. Promote the winner → a transform pipeline exists with those steps.
10. Attach a nightly schedule; force a lower score and confirm
    `completed_with_warnings` plus a drift marker.

## Risks and the calls made

- **Judge-labeled ground truth is circular.** Tagged permanently, surfaced as a
  warning above 50%, never silently mixed with human labels.
- **Consensus pseudo-labels inherit shared bias.** Three variants of the same
  base model agreeing means little. The bootstrap UI requires variants to differ
  by *provider*, not just prompt, before offering auto-accept.
- **Sweep cost.** Hard cell cap, pre-flight estimate, mandatory confirmation,
  and the extract cache doing the heavy lifting.
- **Scoring must be deterministic** even though extraction is not. Comparators
  are pure functions; `llm_judge` results are cached by
  `(expected, actual, judge_config)` so a re-score never moves.
- **Not doing**: a general-purpose eval platform for arbitrary ML tasks, a
  human-labeling workforce product, or model fine-tuning on collected labels.
  The harness stays scoped to "which extraction config should I ship."
