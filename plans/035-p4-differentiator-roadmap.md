# Plan 035 — P4 differentiator roadmap

Covers P4 #38–43 from `plans/027-p0-p4-status-ladder.md` as a **sequencing document**, not per-item design. Each individual item will spawn its own `plans/03N-*.md` when picked up.

## Framing

P0-P3 buy us "GA-grade platform". P4 is competitive positioning. Reference points:

- **dbt** — the SQL-transform incumbent. DTE's advantage: no SQL required for common ops, live preview, multi-source joins without warehouses.
- **Fivetran** — the ELT incumbent. DTE's advantage: transformations happen in-flight, not "load raw then transform later".
- **Prefect / Airflow** — orchestration incumbents. Not our lane; we're not an orchestrator.

The P4 items are bets on which of these axes we push into. Not all six ship.

## Item MVPs

### #38 Streaming source support (CDC / Kafka / webhooks)

- **MVP**: a `kafka` source type that materialises a bounded slice into DuckDB per run (batch-mode consumption). Not true streaming — just "consume up to N messages or T seconds, then transform".
- **First signal**: any customer asks "does DTE do CDC?" more than once.
- **Unknown**: how much of the existing dlt state model transfers to streaming semantics.

### #39 Embedded pipeline SDK

- **MVP**: `packages/dte-sdk` (scaffolded — plan 025) publishes a Python package that lets an external caller define a Pipeline in-process, compile it, and execute against their own DuckDB/Trino. No API server needed.
- **First signal**: any customer says "we want your compiler but our own orchestration".
- **Unknown**: how much of `dte/` package needs to travel with the SDK.

### #40 Plugin / step marketplace

- **MVP**: a pluggy-based registry loading `dte-step-*` packages at startup. Adds one step op per plugin, registered against the compiler dispatch.
- **First signal**: contributors write us step ops we don't have (custom lookup providers, industry-specific enrichers).
- **Unknown**: sandbox story — plugins as arbitrary Python is a supply-chain vector. Trusted-plugins-only for MVP.

### #41 AI-assisted pipeline authoring

- **MVP**: a natural-language field in the builder — "get me orders from the last 7 days joined with customer country" — that returns a proposed step list the user accepts / rejects. Uses tool-use to call our existing schema + step models. Backed by Claude / GPT-4o.
- **First signal**: builder abandonment tracked via analytics — users stuck between "I know what I want" and "I know which steps compose it".
- **Unknown**: prompt engineering per source-schema; hallucinated field names.

### #42 Cost visibility per pipeline / per run

- **MVP**: each run records `bytes_read_per_source`, `bytes_written`, `compute_seconds`, and a coarse `estimated_cost_usd` derived from a lookup table of source-type → per-GB cost.
- **First signal**: any customer asks "which of my pipelines is the most expensive?" — trivial to answer with the data model already in place plus one join.
- **Unknown**: real cost attribution when a Trino query hits partitions we don't control the pricing of.

### #43 Version-controlled pipeline history + diff view

- **MVP**: every `PUT /api/pipelines/{id}` inserts a row into `pipeline_revisions` (id, pipeline_id, config JSONB, changed_by, changed_at). A run pins to a revision id. UI adds a "history" tab with side-by-side JSON diff.
- **First signal**: literally any customer runs DTE for a month — inevitable question is "why did this pipeline start behaving differently?"
- **Unknown**: storage cost of retaining every revision indefinitely (mitigate: keep last 100 + one per month afterward).

## Sequencing (recommended order)

1. **#43 pipeline history + diff** — smallest scope, every customer notices immediately, unblocks the "why did this break?" support workflow.
2. **#39 SDK** — plan 025 already scaffolded; finishing it lets us pitch DTE as "compiler-you-embed" alongside "product-you-run".
3. **#42 cost visibility** — cheap to build on top of existing run metrics + observability plan 031. Immediate CFO-friendly demo material.
4. **#41 AI authoring** — biggest UX bet. Needs #43 (learn from prior revisions) and #39 (SDK exposes the pipeline object shape to LLM tools). Do it once the platform is stable enough that the LLM's failure modes stand out.
5. **#38 streaming sources** — wait for a customer with a real Kafka topic to co-design with.
6. **#40 plugin marketplace** — ecosystem move. Needs external interest before we spend on the sandbox / trust model.

## Dependencies between items

```
#43 history  ─┐
              ├──► #41 AI authoring
#39 SDK  ────┘

#31 obs (P3) ──► #42 cost visibility

#22 pooling (P2) ──► #38 streaming (long-lived Kafka consumers need pool primitives)
```

## Non-goals for each

- **#38**: sub-second latency (we're batch-oriented).
- **#39**: matching a full Beam/Spark API surface — this is a compiler wrapper, not an alternative framework.
- **#40**: user-uploaded plugins (untrusted code).
- **#41**: fully-autonomous pipeline authoring — human-in-the-loop always.
- **#42**: exact cloud-bill reconciliation (accountants own that).
- **#43**: git-like branching / merging of pipelines (linear history only).

## Task list for the top-3

- `plan/036-pipeline-history-and-diff.md` — spec first, then `feature/history-model`, `feature/history-ui`.
- `plan/037-sdk-complete.md` — finish plan 025's SDK scaffold (already has `packages/dte-sdk`, `feature/sdk-move-core` worktree exists).
- `plan/038-cost-visibility.md` — spec the metric taxonomy and the cost-lookup table.

## Kill conditions

If after two design partners neither asks about AI authoring or plugins, defer both indefinitely. The bets that pay off in year 1 are #43 + #42; the rest are speculative.
