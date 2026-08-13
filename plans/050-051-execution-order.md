# Execution order — plans 050 + 051

Merged, priority-ordered backlog across
`050-unstructured-extract-and-structure.md` and
`051-extraction-eval-harness.md`. Task IDs reference the source plans
(`050.4` = plan 050, task 4).

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

| # | Task | Src | Size | Notes |
|---|---|---|---|---|
| 1 | Fix `_detect_format` fallback to raise on unknown extension | 050.3 | S | **Live bug today** — `*.pdf` silently routes into `read_json_auto`. Independently shippable, do it first. |
| 2 | `evals/comparators.py` + `evals/scoring.py` + unit tests | 051.5 | M | Pure functions, zero dependencies, highest test value in either plan. Also unlocks the cheap validation path below. |
| 3 | `artifacts/` store + `GET /api/artifacts/{key}` | 050.1 | M | Every caching claim in both plans rests on this. |
| 4 | `pypdf` / `pdfplumber` providers + registry | 050.2 | M | Deterministic, free, offline. |
| 5 | `documents` source kind + `_load_documents` | 050.3 | S | Listing only — must not parse. Verify schema-infer stays <1s. |
| 6 | `BaseEngine.apply_enrichment` seam + `ExtractStep` + `_apply_extract` | 050.4 | L | ⚠️ **Highest architectural risk in either plan.** The laziness break. |
| 7 | Extract unit tests w/ fixture PDF (TDD — write before 6) | 050.5 | M | Block count, page numbers, cache hit on second call. |

> **Gate A.** Does `apply_enrichment` compose cleanly with ibis? Is a second run
> genuinely free? Does schema inference stay instant? If the seam is ugly, stop
> and redesign — everything downstream assumes it.

**Cheap validation available here:** with tasks 2 + 4 + 5 done you can hand-type
a 20-row CSV of expected values and score two extraction configs from a script.
That answers "do metrics tell me anything the eye doesn't?" for a day of work,
before committing to P3–P5.

---

## P1 — First real capability. API keys enter here.

| # | Task | Src | Size | Notes |
|---|---|---|---|---|
| 8 | `llm_api` connection type + cred spec + compat maps | 050.6 | S | Rides the existing Connection/`EncryptedJSON` path. |
| 9 | `claude` / `openai` / `regex` structure providers | 050.7 | L | JSON-Schema derivation, provenance extraction, retry/backoff, per-row error capture. |
| 10 | `StructureStep` + compiler branch + cost accounting | 050.8 | M | Cost governor lands with it, not after. |
| 11 | Frontend: `ExtractEditor` / `StructureEditor` + field builder | 050.10 | L | `pnpm gen:types` first. |
| 12 | Scenario tests with stub provider | 050.13 | M | Hermetic. No live calls in CI, ever. |

---

## P2 — The trust layer. This is what makes it a product.

| # | Task | Src | Size | Notes |
|---|---|---|---|---|
| 13 | Document inspector + provenance highlighting + `JsonCell` artifact refs | 050.12 | L | **Promoted above variant compare** — it's the differentiator, and 051's labeling loop depends on it. |
| 14 | `POST /api/steps/structure/try` | 050.9 | M | |
| 15 | Variant Compare grid with disagreement highlighting | 050.11 | M | Much weaker without 13 shipped first. |

> **Gate B.** With the inspector in hand, does visual verification already answer
> your questions? If yes, 051 may be premature and 050 alone is the product.
> This is a real possible outcome — decide here, not by momentum.

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

## Parallelisation

- Task 2 (comparators) shares nothing with the rest of P0 — hand it to a second
  person or do it while blocked.
- Within P1, task 11 (frontend editors) only needs the wire shapes from task 10,
  not its implementation.
- P4 labeling paths (25, 26, 27, 28) are mutually independent once 23 lands.
