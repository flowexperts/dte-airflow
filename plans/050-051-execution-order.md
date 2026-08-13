# Execution order — plans 050 + 051

Merged, priority-ordered backlog across
`050-unstructured-extract-and-structure.md` and
`051-extraction-eval-harness.md`. Task IDs reference the source plans
(`050.4` = plan 050, task 4).

> **Status as of 2026-08-13.** P0 complete, P1 complete except task 8 (see
> below), all merged to `main` at `d579e73`. 942 unit tests, 66/67 scenarios
> (the one failure predates this work). Next four, in the agreed order:
> **13 → 16–19 → 41 → 14/15**.
>
> **Gate A: PASSED.** The materialize-map-rejoin seam holds. Measured, not
> asserted: 25 PDFs list in 173ms without parsing; a cached extract re-run is
> 12.2× faster; a cached structure re-run is **213× faster** (9.4s → 0.044s)
> and byte-identical apart from `structure_meta` correctly reporting
> `cached: true`. Schema inference stays instant because listing parses
> nothing. The seam did not need redesigning.
>
> **Task 8 was not built as specified.** No `llm_api` connection type exists.
> Keys currently come from `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in the
> environment. This is a deliberate deferral, not an oversight — see task 42
> and `plans/052-model-provider-connections.md`, which supersedes 050.6.

Ordering principles, in precedence order:

1. **Retire architectural risk first.** The materialize-map-rejoin seam either
   works or the plan changes shape. Prove it before building on it.
2. **Everything that needs no API key comes first.** Free, hermetic, fast to
   iterate, and it means cost enters the picture only after the shape is settled.
3. **Dependency order** within a tier.
4. **Value per unit effort** as the tiebreak.

Sizes: **S** ≈ hours · **M** ≈ 1–3 days · **L** ≈ a week+.

---

## P0 — De-risk. No API keys, no cost, nothing blocks these.

| # | Task | Src | Size | Status |
|---|---|---|---|---|
| 1 | Fix `_detect_format` fallback to raise on unknown extension | 050.3 | S | ✅ `UnsupportedFileFormat` |
| 2 | `evals/comparators.py` + `evals/scoring.py` + unit tests | 051.5 | M | ✅ 57 tests |
| 3 | `artifacts/` store + `GET /api/artifacts/{key}` | 050.1 | M | ✅ 25 tests |
| 4 | `pypdf` / `pdfplumber` providers + registry | 050.2 | M | ✅ 27 tests |
| 5 | `documents` source kind + `_load_documents` | 050.3 | S | ✅ lists without parsing |
| 6 | `BaseEngine.apply_enrichment` seam + `ExtractStep` + `_apply_extract` | 050.4 | L | ✅ Gate A passed |
| 7 | Extract unit tests w/ fixture PDF (TDD — write before 6) | 050.5 | M | ✅ hand-rolled `pdf_builder` |

**Cheap validation was taken, and it paid.** Scoring the shipped regex and
Claude configs against 5 labelled invoices returned macro-F1 1.000 for both —
and the harness still refused to declare a winner, because the Wilson interval
at n=5 reaches to 0.839. That refusal is the behaviour worth trusting, and it
was cheaper to confirm here than after building P3–P5.

---

## P1 — First real capability. API keys enter here.

| # | Task | Src | Size | Status |
|---|---|---|---|---|
| 8 | ~~`llm_api` connection type~~ | 050.6 | S | ❌ **superseded by task 42 / plan 052.** Env vars today. |
| 9 | `claude` / `openai` / `regex` structure providers | 050.7 | L | ⚠️ **partial** — retry/backoff never landed. See task 41. |
| 10 | `StructureStep` + compiler branch + cost accounting | 050.8 | M | ⚠️ **partial** — tokens are captured on `StructureResult` but nothing persists them. See task 43. |
| 11 | Frontend: `ExtractEditor` / `StructureEditor` + field builder | 050.10 | L | ✅ + `documents` source editor |
| 12 | Scenario tests with stub provider | 050.13 | M | ✅ 6 scenarios, regex provider, hermetic |

**Where 9 and 10 fell short is recorded rather than quietly closed.** Both were
marked done and neither was complete: the providers have no retry, and cost
accounting captures token counts that nothing reads. Tasks 41 and 43 carry the
remainder.

---

## P2 — The trust layer. This is what makes it a product.

**Agreed build order from here: 13 → 16–19 → 41 → 14 → 15.** Note this
interleaves P2 and P3 deliberately; the tables below keep their original
grouping so the source-plan mapping stays readable.

| # | Task | Src | Size | Notes |
|---|---|---|---|---|
| 13 | Document inspector + provenance highlighting + `JsonCell` artifact refs | 050.12 | L | **NEXT.** The differentiator, and 051's labeling loop depends on it. Provenance is already captured and currently unread — see the readiness notes below. |
| 14 | `POST /api/steps/structure/try` | 050.9 | M | Single-document iteration without saving a pipeline. |
| 15 | Variant Compare grid with disagreement highlighting | 050.11 | M | Much weaker without 13 shipped first. |

> **Gate B.** With the inspector in hand, does visual verification already answer
> your questions? If yes, 051 may be premature and 050 alone is the product.
> This is a real possible outcome — decide here, not by momentum.

---

## P2.5 — Found by running it. Not in the original plans.

Every one of these came from a real run rather than review. They are listed
where they were found rather than folded into the tidy tiers, because that
provenance is the argument for taking them seriously.

| # | Task | Size | Notes |
|---|---|---|---|
| 41 | **Retry with backoff on 429 / 529** | S | **Third in the build order.** A live `claude-opus-5` call returned `529 Overloaded` on the very first attempt of the session; today that nulls a row silently and the run still reports `completed`. Any corpus beyond a handful will hit it. Honour `retry-after`, cap attempts, and record the retry in `structure_meta` so a slow run is explicable. Everything above this is untrustworthy at scale without it. |
| 42 | Model providers as Connections | M | Plan 052. Supersedes task 8. The live issue is not convenience: `params.api_key` is the only path in DTE that writes a secret to the database in plaintext, and the connection delete-guard does not scan pipeline steps. |
| 43 | Persist per-run token usage and cost | S | `StructureResult` already carries `input_tokens` / `output_tokens`; nothing reads them. Until this lands, 051's sweep cost pre-flight is an estimate with no ground truth to calibrate against. |
| 44 | Artifact cache eviction | M | Artifacts are never garbage-collected. Every prompt iteration leaves its predecessors behind permanently — 5 documents × 4 configs already produced 20 structure artifacts. Needs an LRU or age policy plus a size metric. No user-visible symptom until a disk fills. |
| 45 | `POST /api/destinations` must validate `connection_id` exists | S | Sources return 422 for a non-existent connection; destinations return **201** and store a dangling reference that fails only at run time. Found by fat-fingering `local_fs` for `local-fs`. Fix both the single and bulk paths. |
| 46 | Scenario test that posts what the builder actually posts | S | The blank-id bug reached a running system because every scenario test passes typed, explicit ids, while `emptySource()` sends `{"id": ""}`. A test whose payloads are generated from the frontend's own helpers would have caught it. This is the class of bug the suite is currently blind to. |
| 47 | Fixture PDFs should contain real line breaks | S | `pdf_builder` writes `\n` inside a text-showing operator, so pdfplumber renders it as `(cid:10)`. Harmless for the current assertions, but it makes the fixtures an unfaithful stand-in for real PDFs and forced a contorted regex during the demo. Use per-line `Td` offsets. |

---

---

## Ready to start

Concrete definitions for the next four items, in build order. Everything below
was checked against the code on `main`, not inferred from the plans.

### 13 — Document inspector (`feature/050-document-inspector`)

**⚠️ Blocked on a prerequisite that does not exist yet.** `_apply_extract`
emits `artifact_ref = f"artifact://{dk}"` where `dk = doc_key(content)` — the
hash of the original PDF — but only the *derived* extract key is ever written
to the store. Verified against the live cache: all 25 artifacts are
`application/json`; no key equals a document hash. So `GET /api/artifacts/{dk}`
404s today and the inspector has nothing to render.

- **13a** (S, do first) — `store.put(dk, content, media_type)` in
  `_apply_extract`, guarded by `store.exists(dk)`. Test: after an extract run,
  `GET /api/artifacts/{doc_key}` returns the original bytes with the right
  content type. Note this changes cache growth from text-sized to
  document-sized, which makes task 44 (eviction) more pressing, not less.
- **13b** (M) — `/documents/[key]` route: render the page, overlay the
  provenance boxes. Data is already there: `structure_meta.fields[name] =
  {confidence, page, char_start, char_end, quote}`, and `pdfplumber` blocks
  carry `bbox`. `char_start`/`char_end` index into the *joined* block text, so
  the inspector must reproduce that join (`"\n\n".join(...)`, see `_joined`)
  to map an offset back to a word box — otherwise highlights land in the wrong
  place. `pypdf` returns `bbox: None`; fall back to showing the quote without
  a box rather than guessing a rectangle.
- **13c** (S) — `JsonCell` renders `artifact://` refs as links.
- **13d** (S) — reach it from the run output table and from Preview.

**Acceptance**: click any extracted field, see the exact region of the source
page it came from. A field the model paraphrased has no span and must say so
rather than highlighting an approximation — a wrong highlight is worse than
none, which is why every provider already returns `None` instead of inventing
one.

### 16–19 — Eval storage (`feature/051-eval-core`)

Backend only, no UI. Turns the throwaway scoring script into persisted runs.

- **16** — Alembic `034`: `eval_sets`, `eval_examples`, and five `runs`
  columns. ⚠️ `runs` is hand-written SQL: the columns must land in the
  `SELECT` list in `PostgresRunStore` (used by both `get` and
  `list_for_pipeline`), in the `update` jsonb tuple, **and** in the migration.
  There is no `Run` SQLModel, so nothing catches a miss. Tenant pattern per
  `032_schedules`: `tenant_id NOT NULL DEFAULT 'default'`, `FORCE ROW LEVEL
  SECURITY`, `tenant_isolation` policy.
- **17** — `models/eval.py`, two-class SQLModel pair. Apply
  `_blank_id_means_generate` from the start; it is now the house rule.
- **18** — stores + fakes.
- **19** — `PostgresRunStore` columns + `list_for_eval_set`.

**Acceptance**: label the 5 sample invoices through the API, trigger an eval
run, read macro-F1 back off the run row — reproducing
`scratchpad/score_invoices.py` with nothing hand-written.

### 41 — Retry on 429 / 529 (`feature/050-provider-retry`)

Smallest of the four and the one that makes the rest trustworthy. Honour
`retry-after` when present, exponential backoff with jitter otherwise, cap
attempts (default 3), and surface the count in `structure_meta` so a slow run
explains itself. Test with a stubbed transport that fails twice then succeeds;
no live calls. Both SDKs retry some statuses internally — check before adding a
second layer, and configure theirs rather than wrapping it if so.

### 14 / 15 — Try endpoint and Compare grid

Unchanged from the P2 table. 15 depends on 13 for its per-field drill-down.

---

## P3 — Eval core. Backend only, no UI.

| # | Task | Src | Size | Notes |
|---|---|---|---|---|
| 16 | Alembic `034`: `eval_sets`, `eval_examples`, 5 new `runs` columns | 051.1 | M | ⚠️ `runs` is raw SQL — columns must land in the `SELECT` list, the `update` jsonb tuple (`postgres.py:161`), *and* the migration. Nothing catches a miss. |
| 17 | `models/eval.py` two-class SQLModel pair | 051.2 | S | |
| 18 | `EvalSetStore` / `EvalExampleStore` + Postgres impls + fakes | 051.3 | M | |
| 19 | `PostgresRunStore` new columns + `list_for_eval_set` | 051.4 | S | |
| 20 | `pipeline_type: "eval"` + `_validate_steps` allowances | 051.6 | S | |
| 21 | `_run_body` eval branch: materialise labels, join, score, persist | 051.7 | L | Mirrors `evaluate_contracts`. |
| 22 | `config_digest` + regression comparison vs prior run at same digest | 051.8 | M | Needed before the leaderboard can group. |
| 23 | `routes/evals.py` — CRUD, leaderboard, field failures | 051.9 | M | Sweep endpoint deferred to P5. |
| 24 | Eval-run scenario tests, stub provider | 051.10 | M | |

---

## P4 — Labeling. Ordered by leverage, not by plan order.

| # | Task | Src | Size | Notes |
|---|---|---|---|---|
| 25 | Inspector accept / fix → `POST /eval-sets/{id}/examples` | 051.11 | M | **Cheapest and highest leverage** — labeling as a byproduct of reviewing. |
| 26 | CSV / JSONL import with filename→`doc_key` hashing | 051.13 | S | Trivial, and the only path if labels already exist elsewhere. |
| 27 | Consensus bootstrap + review queue population | 051.12 | L | The afternoon-not-a-week unlock. Requires provider-diverse variants. |
| 28 | LLM-judge proposal path + >50% warning | 051.14 | M | **Lowest priority of the four** — circularity risk, most speculative. |

> **Gate C.** Is n large enough that the leaderboard says anything? If Wilson
> intervals still overlap on every pair, more labels beats more UI.

---

## P5 — Eval surfaces + sweeps.

| # | Task | Src | Size | Notes |
|---|---|---|---|---|
| 29 | `pnpm gen:types`, api.ts helpers, sidebar entry | 051.15 | S | |
| 30 | `/evals` list + `/evals/[id]` tab shell | 051.16 | M | |
| 31 | Leaderboard: tie-within-noise, holdout column, per-field drill-down | 051.17 | L | The honesty guardrails are here — build them, don't document them. |
| 32 | Examples + Review tabs, keyboard-driven | 051.18 | M | |
| 33 | Sweep endpoint + launcher with cost pre-flight confirmation | 051.19 | M | |
| 34 | Promote-to-pipeline | 051.20 | S | Closes the loop. |

---

## P6 — Deferred axes. Reassess before starting any of these.

| # | Task | Src | Size | Notes |
|---|---|---|---|---|
| 35 | Scheduled eval regression + drift surfacing | 051.21 | M | Nearly free once P3–P5 exist; worthless before a stable eval set. |
| 36 | `chunk` op | 050.15 | M | **Only if RAG is actually the product.** Different use case from extraction→warehouse. |
| 37 | `EmbedStep` + embedding providers | 050.14 | L | ″ |
| 38 | `PgVectorTarget` + writer (+ collection metadata, index config, metadata fields) | 050.16 | M | ″ |
| 39 | `transcribe` provider + audio inspector | 050.17 | L | Genuinely last. |
| 40 | Image / vision extract + frame-strip inspector | 050.18 | L | ″ |

---

## Critical path

The shortest route to something worth showing anyone:

**1 → 3 → 4 → 5 → 7 → 6 → 8 → 9 → 10 → 11 → 13**

That is P0 plus P1 plus the inspector: documents in, typed columns out, with
click-to-see-where-it-came-from. Everything after that is measurement,
labeling, and scale.

**Everything up to 11 is done and merged.** The remaining step on this path is
13, plus its unlisted prerequisite 13a. Task 8 was skipped rather than
completed; that is a live plaintext-secret issue, not a deferral of polish.

## Parallelisation

- Task 2 (comparators) shares nothing with the rest of P0 — hand it to a second
  person or do it while blocked.
- Within P1, task 11 (frontend editors) only needs the wire shapes from task 10,
  not its implementation.
- P4 labeling paths (25, 26, 27, 28) are mutually independent once 23 lands.
