# Backend (`dte`)

All paths relative to `backend/`.

## Architecture

DTE is a batch data transformation engine. A **Pipeline** (Pydantic model) describes sources, ordered transform steps, and an output target.

### Full data flow

```
DltSource config(s)
    ↓
dlt_loader.load_source() → ibis.Table per source (loaded into shared DuckDB connection)
    ↓
compile_pipeline(pipeline, tables) → ibis.Table (transformed)
    ↓
DuckDBEngine.execute_to_json() → output file + row count
```

### Key modules

**`dte/models/pipeline.py`** — the pipeline spec. `Pipeline.steps` is `list[dict]` (not a typed Union) because the `map` op requires a sub-discriminator on `mode` that Pydantic's discriminated union can't handle with a shared `op` key. The compiler parses each step dict by `op`/`mode`.

**`dte/sources/dlt_loader.py`** — universal source loading. `load_source(DltSource, ibis_con)` returns an `ibis.Table` bound to the shared DuckDB connection. The dispatch splits by source_type:

- **`filesystem`**: `read_json_auto` / `read_csv_auto` / `read_parquet` / `read_xlsx` via `CREATE OR REPLACE VIEW`. No dlt. Nested JSON comes through as STRUCT columns; format is detected by extension (`.json`, `.jsonl`, `.ndjson`, `.csv`, `.tsv`, `.parquet`, `.xlsx`) and `config["format"]` overrides. `.xlsx` uses DuckDB's `excel` extension (lazy `INSTALL excel; LOAD excel;`) and reads only the first sheet.
- **`sql_database`**: DuckDB scanner extensions (`INSTALL sqlite|postgres|mysql; ATTACH … (TYPE …, READ_ONLY); CREATE VIEW`). Scheme detected from the SQLAlchemy-style `credentials` URL. No dlt.
- **`s3`, `gcs`, `azure`**: DuckDB native remote reads. `s3` and `gcs` go through the `httpfs` extension; `azure` through the `azure` extension. Each loader installs the extension, emits `CREATE OR REPLACE SECRET <scoped-name> (TYPE …, …)`, then materialises `bucket_url + file_glob` via `read_json_auto` / `read_csv_auto` / `read_parquet` in a `CREATE OR REPLACE VIEW`. **GCS auth is HMAC-only** — supply `hmac_key_id` + `hmac_secret`; the old `credentials_json` (service-account JSON) is rejected. **Azure auth**: `connection_string` (preferred) or `account_name` + `account_key`.
- **`mongodb`, `rest_api`**: dlt (`@dlt.resource` + `dlt.sources.rest_api.rest_api_source`). Kept because dlt's pagination / normalisation earn their keep for real APIs. Their columns still come through with `__` flattening — refs to them are single-token identifiers, not path expressions.

**`dte/compiler/ibis_compiler.py`** — `compile_pipeline(pipeline, tables)` maintains a **named registry** (`dict[str, ibis.Table]`) instead of a rolling variable. Each step reads from and writes back to the registry via `current_key`. Join steps write their result under `output_id` and update `current_key`. This allows multi-source pipelines.

- Filter and expression-map steps escape to raw SQL via `con.create_view()` + `con.sql()` — Ibis has no SQL string parser. This is the seam for future distributed backends (Spark, Trino).
- Pivot uses `con.con.execute("CREATE OR REPLACE TEMP TABLE ... AS PIVOT ...")` — dynamic PIVOT cannot be a view in DuckDB, and `con.sql()` fails because sqlglot can't subquery a PIVOT node.

**`dte/engine/duckdb_engine.py`** — wraps `ibis.duckdb.connect()`. Exposes `con` property (the ibis backend) for use by `dlt_loader`. Only responsible for execution and output — does not load sources.

**`dte/store/`** — Protocols in `base.py`, one per persisted entity: `PipelineStore`, `SourceStore`, `DestinationStore`, `ConnectionStore`, `RunStore`. `postgres.py` is the sole production backend (SQLAlchemy async, requires `DATABASE_URL`). Tests use `tests/fakes.py` — there is no in-memory store shipped in the package. The active backend is wired in `dte/api/deps.py` and injected into routes via FastAPI `Depends()`. All four Pydantic-modelled stores speak typed SQLModel instances end-to-end (see the **Model + store pattern** subsection below); `PostgresRunStore` still hand-writes SQL because `Run` isn't a Pydantic model yet.

**`dte/api/`** — FastAPI app. Routes use `Depends(get_pipeline_store)` and `Depends(get_run_store)`. Tests override these with `app.dependency_overrides`. `_execute_pipeline` runs as an `asyncio.create_task` — trigger returns `run_id` immediately, caller polls `GET /api/runs/{run_id}`.

### Step dispatch

```python
op = step["op"]    # "filter"|"rename"|"retype"|"map"|"sort"|"aggregate"|"join"|"pivot"|"select"
                   # |"check"|"profile"|"extract"|"structure"
mode = step.get("mode")   # "lookup"|"expression"|"calculation"  — map steps only
```

### Field references and nested columns

Dot syntax is the wire form: `order.amount`, `user.address.city`. `_resolve_field()` splits on `.` and traverses struct members; if the head isn't a top-level column it falls back to the joined `__` name (so `mongodb` / `rest_api` sources — which still flatten via dlt — keep working). `_apply_output_fields` / `_apply_lookup` route through `_resolve_field` so Select and Lookup steps handle struct paths. Struct-path outputs are named after the leaf segment when no alias is given.

To migrate saved pipelines from `parent__child` to `parent.child`:
```bash
cd backend && uv run python scripts/migrate_field_refs.py           # dry run
cd backend && uv run python scripts/migrate_field_refs.py --write   # persist
```

### Ibis version notes

- ibis ≥ 9: use `ibis.cases(*[(condition, value), ...], else_=default)`, **not** `ibis.case()`
- `table.rename({new_name: old_name})` — ibis rename direction is reversed from intuition


### Unstructured: documents, extract, structure (plan 050)

A `documents` source lists files — path, size, modified time — and **parses
nothing**. Extraction happens only when an `extract` step runs, which is what
keeps `POST /api/schema/infer` instant and free while the builder fires it on
every edit.

```
documents source → extract (PDF → text) → structure (text → typed columns)
                                        → every existing step works from here
```

- **`extract`** fans one document out to one row per page (`granularity`).
  Providers: `pdfplumber` (word bounding boxes, needed for provenance
  highlighting) and `pypdf` (faster, text only). A document that fails to
  parse fills `extract_meta.error` and leaves the text NULL — it does **not**
  fail the run. Add a `check` step if you want it fatal.
- **`structure`** turns text into the user's declared fields as real typed
  columns. Providers: `claude`, `openai`, and `regex` (deterministic, free,
  offline, exact provenance — and the only one CI can run).

**These two ops break laziness.** Every other step is a lazy ibis expression;
a model call cannot be. They go through `BaseEngine.apply_enrichment`
(`dte/engine/base.py`), which materialises, maps in Python, and registers the
result back — the same shape as `_apply_check_step` and `_apply_profile`.
`TrinoEngine` raises `EnrichmentNotSupportedOnBackend`.

**Caching is the whole economic argument.** Extract results are keyed by
document content; structure results by `sha256(text)` + the entire structure
config. So downstream steps (`select`, `filter`, `aggregate`) are free to
iterate on, and editing a prompt never re-parses a PDF. But there is no
partial reuse: changing one field's description re-calls the model for every
field on every row. Artifacts are never garbage-collected today.

`DTE_ARTIFACT_DIR` **must** point at storage shared by the API and the
workers. It defaults to the relative `.dte-artifacts`, which resolves inside
each container — backend and worker then keep separate caches and Trigger
re-pays for what Preview bought. Compose mounts a named volume; the Dockerfile
creates the directory owned by `dte` so the fresh volume inherits that
ownership (a root-owned volume fails silently for the non-root process).

**Demo/test `documents` corpora live in `backend/sample_data/`, never
`/tmp`.** `/tmp` gets swept — macOS, CI, a reboot — and a `documents` source
pointed there finds zero files with no error (it just lists nothing). Worse,
`eval_examples.doc_key` is `sha256(document bytes)`, so losing the files
orphans every label with no way to reproduce the exact bytes they were keyed
against. `backend/sample_data/eval-demo/invoices/` is committed to git,
regenerated deterministically by `backend/scripts/generate_eval_demo_invoices.py`
(built on the same `tests/fixtures/pdf_builder.build_pdf` the test suite
uses), and bind-mounted read-only into `backend` and `worker` at
`/app/sample_data`. If you add a new demo/test PDF corpus, put it here, not
in a path under `/tmp` — `/tmp/dte-samples` stays reserved for data that is
genuinely regenerated on every bring-up (e.g. `docs/user/scripts/seed.py`'s
JSON fixtures), where losing it on a sweep is a non-event.

**Document inspector** (`/documents/[key]`, and the Inspect action on run
output / preview rows). An extracted row carries three distinct references and
you need all three: `artifact_ref` is the *document* hash, `extract_meta.key`
is the *derived* key holding the cached parse (word boxes, page size), and
`structure_meta.fields` holds per-field provenance. A doc hash cannot be
turned back into a derived key — that needs the provider and every param — so
`/documents/[key]` shows the document alone; highlights need the row, which is
why the table action opens a modal instead of navigating.

Highlight geometry (`frontend/src/lib/provenance.ts`) deliberately ignores
`char_start`/`char_end`. Those index into `page.extract_text()` while boxes
come from `page.extract_words()` — two independent pdfplumber passes with no
guaranteed alignment, so trusting them yields highlights that are subtly off,
which is worse than none: it looks authoritative while pointing at the wrong
number. The quote is matched against the word sequence instead, anchored at
word boundaries, normalising away everything but letters and digits (the page
reads `$1,240.50`; a model quotes `1240.50`). No match → no box, and the UI
says so.

`tests/fixtures/pdf_builder.py` must emit one text operator **per line**. A
newline inside a single `Tj` is not a line break in PDF — pdfplumber decodes
it as `(cid:10)` glued into the neighbouring word, word segmentation
collapses, and every highlight silently fails to resolve.

The artifact route serves **ranged streams** (`Accept-Ranges`, 206, streamed
from `store.open_stream`). pdf.js is opened with `disableAutoFetch` so it
fetches only the pages viewed — without that flag it backgrounds a fetch of
the whole file and the range support buys nothing. `Content-Range` is in CORS
`expose_headers`; omit it and pdf.js silently reverts to whole-document
downloads, which still works and so never surfaces as an error.

**Optional extras**: `[unstructured]` is pypdf + pdfplumber; `[models]` is the
anthropic + openai SDKs. Both are lazy imports, so a missing extra surfaces
only on a real run, never in tests.

**API keys** currently come from `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in the
environment, wired to both `backend` and `worker`. Do **not** put a key in the
step's `params.api_key`: step params are stored unencrypted in
`pipelines.steps` JSONB and copied into every revision. See
`plans/052-model-provider-connections.md`.

