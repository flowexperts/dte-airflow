# Plan 050 — Unstructured data: extract → structure, with inline experimentation

## Context

DTE today is a closed loop over tabular data: every source ends as a DuckDB
view, every step is an ibis expression, everything stays lazy until `execute`.
A grep for `pdf|ocr|embedding|llm|whisper|openai|anthropic|vector` across
`backend/dte` and `frontend/src` returns zero real hits. This is a greenfield
axis, not an extension of an existing one.

The business case: the highest-value data in most orgs is not in Postgres, it
is in PDFs — invoices, contracts, statements, lab reports, claims. Getting it
into a warehouse today means either a human or a bespoke script. DTE already
owns everything downstream of "rows exist": joins, quality contracts,
scheduling, destinations, lineage. Adding a credible unstructured *front end*
turns a good transform engine into the whole pipeline.

The hard part is not calling a model. It is **trust**. Extraction is
non-deterministic, slow, and costs money per row, so the tabular workflow
(edit → dry-run → eyeball 20 rows) collapses: you cannot verify a extracted
`invoice_total` by staring at a table cell, and you cannot afford to re-run 10k
PDFs while tuning a prompt. The plan therefore treats **provenance** and
**cached experimentation** as load-bearing architecture, not polish.

Scope decisions taken with the user:
- **PDF / documents first.** Audio, video, and image land later behind the same
  op seam and the same provider interface.
- **Two ops, not one.** `extract` (file → document blocks, deterministic where
  possible) then `structure` (blocks → the user's declared data model). The
  split is what makes iteration cheap: you tune `structure` prompts without
  re-parsing a single PDF.
- **Pluggable providers, user-picked per step** — deterministic/local OSS
  extractors, Claude, and OpenAI all behind one registry.
- **Experimentation is inline**, attached to the step editor, not a separate lab.
- **All three outputs**: structured rows, a content-addressed artifact store,
  and a vector destination.

## Architecture

### The one thing that changes about the engine

Every existing step is a lazy ibis expression. Enrichment cannot be. A model
call is per-row, slow, rate-limited, retryable, and billable — it must not sit
inside a DuckDB scan where it will be re-evaluated on every downstream
reference.

**Enrichment steps materialize.** The pattern, borrowed verbatim from
`_apply_check_step` (`backend/dte/compiler/ibis_compiler.py:258`) and
`_apply_profile` (`:316`):

```
ibis.to_sql(table) → CREATE TEMP VIEW __enrich_in_N__
  → read the key columns out to Arrow
  → bounded-concurrency async map through the provider (cache-first)
  → write results to a temp table
  → JOIN back on the row key, return an ibis.Table
```

This is a deliberate, documented laziness break — the same one `_apply_pivot`
already makes. It buys retries, per-row progress events, rate limiting, and
caching, all of which are impossible inside a scan.

Add to `BaseEngine` (`backend/dte/engine/base.py`) one abstract method,
mirroring the existing `apply_filter_sql` / `apply_expression_sql` seam:

```python
def apply_enrichment(
    self, table: ibis.Table, spec: EnrichmentSpec, on_progress=None
) -> ibis.Table: ...
```

`DuckDBEngine` implements it. `TrinoEngine` raises
`EnrichmentNotSupportedOnBackend` — same shape as the existing
`RawSqlNotSupportedOnBackend`. Pushdown engines (`postgres`, `bigquery`, …)
already resolve to a `DuckDBEngine` via `engine/registry.py`, so they work.

### Content-addressed artifact store

New module `backend/dte/artifacts/`. One idea:

```
key = sha256(source_bytes)                    → the document itself
key = sha256(doc_key | op | provider | params_canonical_json)  → any derived artifact
```

- `store.py` — `ArtifactStore` protocol: `put(key, bytes, media_type) -> uri`,
  `get(key)`, `exists(key)`, `open_stream(key)`.
- `local.py` — filesystem backend under `DTE_ARTIFACT_DIR`.
- `s3.py` — reuses the credential path already in
  `backend/dte/sources/duckdb_secrets.py`; do not write a second one.

Two consequences fall straight out of the second key form:

1. **Re-running a pipeline is free** for unchanged documents and unchanged
   params. Cache hits are recorded per row so the UI can show
   `18 cached · 2 called · $0.004`.
2. **Experimentation is free after the first pass.** Changing a prompt changes
   the key for `structure` but not for `extract`, so PDF parsing is paid once
   and every variant thereafter costs only the model call it actually needs.

Rows never carry blobs. They carry `artifact://<key>` refs, and the UI streams
bytes back through `GET /api/artifacts/{key}` for rendering.

### Provider registry

New module `backend/dte/providers/`, deliberately shaped like
`sources/loader.py`'s `LOADERS` dict — a flat name→callable registry, not a
class hierarchy.

```python
# providers/base.py
class ExtractProvider(Protocol):
    name: str
    def extract(self, doc: bytes, media_type: str, params: dict) -> ExtractResult: ...

class StructureProvider(Protocol):
    name: str
    def structure(self, blocks: list[Block], schema: DataModel, params: dict) -> StructureResult: ...
```

Phase-1 registry contents:

| name | kind | dep | notes |
|---|---|---|---|
| `pypdf` | extract | `pypdf` | deterministic, free, native-text PDFs |
| `pdfplumber` | extract | `pdfplumber` | adds word-level bboxes → real provenance |
| `tesseract` | extract | `pytesseract` (opt) | scanned PDFs; optional extra |
| `claude` | extract + structure | `anthropic` | vision extract for scans; default structurer |
| `openai` | extract + structure | `openai` | parity option |
| `regex` | structure | — | deterministic escape hatch, testable, free |

All optional deps go in a `pyproject.toml` extra (`dte[unstructured]`); import
lazily inside the provider module so a missing dep is a clear 422 at step
validation, never an import-time crash. Credentials ride the **existing**
Connection model — add `llm_api` to `ConnectionType` with an
`ApiKeyCredentials` entry in `_DLT_CRED_CLASS` (or a local spec if no dlt class
fits). Do not invent a second secrets path; `EncryptedJSON` already handles
encryption at the column level.

### The two ops

**`extract`** — file rows in, one row per *block* out (fan-out). This is the
only op besides `join` that changes row cardinality; call it out in tests.

```json
{"op": "extract", "source_field": "path", "provider": "pdfplumber",
 "granularity": "page",           // page | document | paragraph
 "params": {"ocr_fallback": true},
 "output_field": "content"}
```

Emits: `content` (text), `block_index`, `page`, `bbox` (struct), `artifact_ref`,
`extract_meta` (struct: provider, ms, cached, error). A per-row failure fills
`extract_meta.error` and leaves `content` NULL — **it does not fail the run**.
One bad PDF in 10k must not cost you the batch; a downstream `check` step is
how you make that fatal if you want it to be.

**`structure`** — blocks in, the user's declared data model out. This is the op
that earns the feature.

```json
{"op": "structure", "input_field": "content", "provider": "claude",
 "model": {"fields": [
    {"name": "invoice_total", "type": "float", "description": "grand total incl. tax",
     "required": true, "examples": ["1240.50"]},
    {"name": "issued_on", "type": "date", "description": "invoice issue date"}]},
 "params": {"model": "claude-opus-5"},
 "on_error": "null"}              // null | fail
```

> **Corrected during implementation.** This originally showed
> `"temperature": 0`. Sampling parameters — `temperature`, `top_p`, `top_k` —
> are **rejected with a 400** on Claude Opus 5 and Sonnet 5, so that config
> would have failed on every row. `StructureStep` now rejects them at
> model-parse time, turning a per-document runtime failure into one clear
> validation error at save. Determinism is not available as a knob; steer with
> field descriptions and let the eval harness measure stability instead.

The declared `model.fields` become **real typed columns** — the provider is
handed a JSON Schema derived from them and its output is coerced through the
same `ParamType` vocabulary already in `models/pipeline.py:1009`. From this
column onward the row is ordinary tabular data and every existing step (filter,
join, aggregate, check, pivot) works unchanged. That is the whole point of the
two-op split.

Alongside each declared field, `structure` emits a sibling provenance struct:

```
structure_meta.invoice_total = {confidence, page, char_start, char_end, quote}
```

Provenance is what makes the UI trustworthy and is **required** of every
provider, deterministic ones included (`regex` returns its match span). Do not
let a provider ship without it.

**`embed`** — phase 3, same materializing machinery, emits `float[]` for the
vector destination.

### Backend touch points (the checklist this repo enforces)

Adding an op means exactly three edits, per CLAUDE.md:
1. `models/pipeline.py` — `ExtractStep` / `StructureStep` models + entries in
   `_STEP_MODELS` (`:982`).
2. `compiler/ibis_compiler.py` — branches in `_dispatch_single_table_step`
   (`:190`) + `_apply_extract` / `_apply_structure`.
3. `pnpm gen:types`, then the frontend registry in `steps/types.ts`.

Plus, for the new source kind:
4. `SourceKind` (`:273`), a `DocumentSourceConfig` in `_SOURCE_CONFIG_MODELS`
   (`:327`), and a `_load_documents` entry in `LOADERS`
   (`sources/loader.py:309`).

⚠️ **Live trap**: `_detect_format` (`sources/loader.py:37`) falls back to
`"json"` for unknown extensions, so a `*.pdf` glob today silently routes into
`read_json_auto` and dies with a parse error. Fix that fallback to raise while
you are in there.

`_load_documents` does **not** parse anything. It builds a listing view over
DuckDB's `glob()` TVF — `path, filename, ext, size_bytes, modified_at,
media_type` — one row per file. Extraction happens only when an `extract` step
runs. This keeps `POST /api/schema/infer` instant and free, which matters
because the builder auto-fires it (`AutoInferSchemas`).

### Cost governor

Non-negotiable, because the failure mode is a user losing $200 to a dry-run.

- `preview` / `dry-run` cap enrichment at `limit` rows (default 20) and only
  ever run against the **pinned sample** (below).
- Every enrichment step returns `{calls, cached, est_cost_usd, elapsed_ms}`
  through the existing `on_step` callback; surfaced in the preview response
  next to `step_sqls`.
- `DTE_ENRICHMENT_MAX_CALLS_PER_RUN` (default 50_000) hard-stops a run.
- Cost estimate renders **before** the first uncached run of a step, with the
  document count spelled out: "Will call claude on 1,204 documents · ~$3.60".

### Frontend — experimentation and visual feedback

Per the user's decision this lives **inline in the step editor**, not a
separate surface. Three additions.

**1. `ExtractEditor` / `StructureEditor`** in
`components/builder/steps/editors.tsx`, following the `RetypeEditor` template
(`:935`) and dispatched from the switch at `:1752`. `StructureEditor` is the
substantial one: a repeatable field-row builder (name / type / description /
required), plus provider + model selectors. Per DESIGN precedent 14, breakpoints
are `@container` — these editors get ~534px in the builder split pane.

**2. Pinned sample + variant compare** — the experimentation loop, rendered
inside `StructureEditor` under a `Segmented` **Configure | Compare** (DESIGN
precedent 4: Segmented picks a *mode*).

- Pin K documents (default 5) from the source listing; the pin persists on the
  step as `_sample: string[]` so you return to the same evidence tomorrow.
- Add up to 3 **variants** — provider + model + params triples over the same
  declared data model.
- "Run variants" fires `POST /api/steps/structure/try` for the cross product.
  Because `extract` output is cached by content hash, only the model calls are
  paid.
- Results render as a comparison grid: rows = pinned docs, columns = variants,
  cells = the extracted field set. **Disagreement between variants is
  highlighted** — that is the signal a prompt is unstable, and it is visible at
  a glance with no ground truth required. Per-variant footer: agreement %,
  mean confidence, cost, latency.
- Promote a winning variant into the step with one click.

**3. Document inspector** — the visual-feedback half. A split panel: rendered
PDF page on the left (canvas render via a locally-bundled `pdfjs-dist`; no CDN),
extracted fields on the right. **Click a field → the source page scrolls to it
and the quote span highlights**, driven by the `structure_meta` provenance
struct. This is the single feature that converts "the model said 1240.50" into
"I can see where it got 1240.50", and it is why provenance is mandatory above.

Reached from two places, sharing one component (DESIGN: reuse the rendering
path):
- the Compare grid (click any cell),
- the preview table — extend `JsonCell`
  (`components/ui/json-cell.tsx`, the *only* value renderer, used by both
  `pipeline-preview.tsx` and `run-output-preview.tsx`) to detect
  `artifact://` refs and render a thumbnail chip that opens the inspector.

Also: per-document progress events. `extract`/`structure` emit `RunEvent`s per
batch, which finally gives the `Timeline` primitive
(`components/ui/timeline.tsx`) real data instead of the hardcoded demo at
`app/(app)/preview/page.tsx:234`. While there, collapse the duplicate private
`TimelineRow` inside `components/run/diagnostics.tsx` into the shared primitive
— it is an existing DESIGN violation and this is the moment it starts to matter.

### Vector destination (phase 3)

`PgVectorTarget` in the `OutputTarget` union + `_DEST_FAMILY` /
`_FAMILY_CANONICAL_EXT` entries + an `isinstance` branch in
`engine/writers/__init__.py`. It is not a file target, so the extension
guardrails in `_check_dest_path_extension` (`:379`) do not apply. Also add
`run-output-preview.tsx`'s `SUPPORTED` set — today unsupported types collapse
to a dashed line.

**Why DTE owns `embed` at all.** Vector DBs universally ship the *index*
algorithm (HNSW / IVFFlat / DiskANN) — never reimplement that. But only some
of them generate embeddings (Weaviate, Chroma, Pinecone, LanceDB do; pgvector,
Qdrant core, and Atlas Vector Search do not). Delegating embedding to the DB
would mean the DB owns the model choice, which makes embedding-model A/B
testing impossible, re-embeds on every upsert instead of hitting our cache, and
locks the corpus to one vendor. Supplying pre-computed vectors is also the only
interface *every* vector DB accepts. Chunking, meanwhile, is the dominant lever
on retrieval quality and is a transform — squarely DTE's job.

That choice creates one obligation and two gaps, all three of which are part of
the phase-3 deliverable:

1. **Collection metadata must record embedding identity.** DTE is not in the
   read path, and a query embedded with a different model than the corpus
   silently degrades retrieval rather than failing. So the collection is
   self-describing: persist `{model, provider, dimension, normalized,
   chunk_params}` as collection metadata at creation, for the retrieval side to
   read back instead of hardcoding and drifting. Same discipline as the
   provenance requirement — make the artifact carry its own contract.
2. **Index config belongs on the destination.** Expose `distance_metric`
   (`cosine` | `l2` | `inner_product`) plus HNSW `m` / `ef_construction`. A
   wrong distance metric is a silent quality failure — it retrieves, just badly
   — so it must be explicit rather than invisibly defaulted.
3. **Carry metadata columns alongside the vector.** Filtered retrieval ("2024
   contracts from vendor X") needs the structured fields next to the embedding,
   and those are exactly what `structure` already produced. The writer takes a
   configurable `metadata_fields: list[str]` rather than dropping everything but
   `id` and `vector`.

## Task list

Each phase is a worktree per CLAUDE.md: `git worktree add ./worktrees/<name> -b feature/<name>`.

### Phase 1 — foundation: documents in, text out (`feature/050-document-source`)
1. `dte/artifacts/{__init__,store,local}.py` + `GET /api/artifacts/{key}` + tests.
2. `dte/providers/{__init__,base,pypdf_provider,pdfplumber_provider}.py`, registry + tests.
3. `SourceKind += "documents"`, `DocumentSourceConfig`, `_load_documents` in `LOADERS`.
   Fix the `_detect_format` json fallback.
4. `ExtractStep` model + `_STEP_MODELS` + `_apply_extract` + `BaseEngine.apply_enrichment`
   + `DuckDBEngine` impl + `TrinoEngine` raise.
5. Unit tests **first** (TDD is a repo convention): a 3-page fixture PDF under
   `tests/fixtures/`, exact-match assertions on block count, page numbers, cache
   hit on second call.

### Phase 2 — structure + inline experimentation (`feature/050-structure-op`)
6. `llm_api` connection type + credential spec + compat map entries.
7. `claude`/`openai`/`regex` structure providers; JSON-Schema derivation from
   `model.fields`; provenance extraction; retry/backoff; per-row error capture.
8. `StructureStep` + compiler branch + cost accounting through `on_step`.
9. `POST /api/steps/structure/try` (sample × variants, cache-first).
10. Frontend: `pnpm gen:types`, `StepOp`/`STEP_OPS`/`emptyStep`, `ExtractEditor`,
    `StructureEditor` + data-model field builder.
11. Frontend: variant Compare grid with disagreement highlighting.
12. Frontend: document inspector with provenance highlighting; `JsonCell`
    `artifact://` handling.
13. Scenario tests under `tests/scenarios/steps/` with a **stub provider** —
    the suite must stay hermetic and free; no live API calls in CI.

### Phase 3 — embeddings + vector out (`feature/050-embed-and-vector`)
14. `EmbedStep` + embedding providers (local `sentence-transformers` + hosted).
15. `chunk` op (token-window with overlap) — the second fan-out op.
16. `PgVectorTarget` + writer + `run-output-preview` support.

### Phase 4 — other modalities (`feature/050-audio-video`)
17. `transcribe` provider kind (whisper local + hosted), timestamped segments
    as provenance; `<audio>` scrubbing in the inspector reusing the same
    click-provenance-highlight contract.
18. Image/vision extract; frame-strip inspector.

## Files touched

**New**: `backend/dte/artifacts/*`, `backend/dte/providers/*`,
`backend/dte/api/routes/artifacts.py`, `backend/tests/unit/test_extract_step.py`,
`test_structure_step.py`, `backend/tests/fixtures/*.pdf`,
`frontend/src/components/builder/steps/structure/*` (editor, variant grid),
`frontend/src/components/document-inspector/*`, alembic migration for the
`llm_api` connection type if any enum is DB-side.

**Modified**: `backend/dte/models/pipeline.py` (`SourceKind`, `ConnectionType`,
`_SOURCE_CONFIG_MODELS`, `_DLT_CRED_CLASS`, `_STEP_MODELS`, `OutputTarget`,
compat maps), `backend/dte/sources/loader.py` (`LOADERS`, `_detect_format`),
`backend/dte/compiler/ibis_compiler.py` (`_dispatch_single_table_step` + two
`_apply_*`), `backend/dte/engine/{base,duckdb_engine,trino_engine}.py`,
`backend/dte/engine/writers/__init__.py`, `backend/dte/api/routes/pipelines.py`
(cost fields on preview), `backend/pyproject.toml` (extras),
`frontend/src/components/builder/steps/{types.ts,editors.tsx,summary.tsx}`,
`frontend/src/components/builder/sources/{types.ts,SourceEditor.tsx}`,
`frontend/src/components/ui/json-cell.tsx`,
`frontend/src/components/run/diagnostics.tsx`,
`frontend/src/lib/{api.ts,api-types.ts}`, `CLAUDE.md`, `frontend/DESIGN.md`.

**Deleted**: none.

## Verification

```bash
# Unit — fast loop, no network
cd backend && uv run pytest tests/unit/test_extract_step.py tests/unit/test_structure_step.py -x

# Full default suite must stay green (scenarios excluded by addopts)
cd backend && uv run pytest

# Scenario suite, stub provider only — asserts no live calls
cd backend && uv run pytest tests/scenarios -m scenario -k "extract or structure" -v

# Whole stack
docker compose up -d --build
```

End-to-end, by hand — the acceptance run:
1. Drop 5 invoice PDFs in a local dir; create a `documents` source pointing at
   it. **Infer schema returns in <1s and costs nothing** — proves listing is
   lazy.
2. Add `extract` (provider `pdfplumber`, granularity `page`). Dry-run: 5 rows
   in, N page-rows out, `content` populated, `page`/`bbox` set.
3. Add `structure` with a 3-field model. Pin the 5 docs, add two variants
   (`claude` vs `regex`), Run variants. Assert: grid renders, disagreements
   highlighted, cost shown.
4. Click a cell → inspector opens, PDF page renders, clicking `invoice_total`
   highlights the source quote on the page.
5. Re-run the same variants → all cells report **cached**, cost $0. This is the
   single most important assertion in the plan; if it fails, experimentation is
   unaffordable and the feature does not work.
6. Add a `check` step (`invoice_total > 0`) and a json destination. Trigger.
   Run detail shows a real per-document Timeline and rows land in the output.
7. Corrupt one PDF, re-run: that row has `extract_meta.error` set, the other
   four succeed, run status is `completed`.

## Risks and the calls made

- **Laziness break** — enrichment materializes. Accepted; documented in
  CLAUDE.md alongside the existing `_apply_pivot` note.
- **Optional deps balloon the image.** All unstructured deps sit behind a
  `dte[unstructured]` extra and lazy imports; the distroless runtime (plan-036)
  gets a separate tag rather than a fatter default image.
- **Non-determinism vs. the scenario suite.** Every scenario test uses a stub
  provider with recorded fixtures. Live-provider tests are a separate opt-in
  marker, never in CI.
- **`temperature: 0` is not determinism.** Do not claim reproducibility in the
  UI; show confidence and provenance instead, and let `check` steps be the
  enforcement mechanism.
- **Not doing**: a chat interface, agentic multi-step reasoning, or a document
  labelling/annotation tool. The op stays a pure function of
  (document, data model, provider) so it remains cacheable, testable, and
  schedulable — which is what makes it a *pipeline* step rather than a demo.
