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

- Filter and expression-map steps escape to raw SQL via
  `table.alias(name).sql(fragment, dialect="duckdb")` — Ibis has no SQL string
  parser. The alias form matters: it rides on **the table's own backend** and
  sqlglot transpiles the DuckDB-dialect fragment to whatever that backend
  speaks, so an Advanced filter or a map/expression works unchanged against a
  `sql_database` source. It also writes nothing to the user's database.
  It used to be `con.create_view()` + `con.sql()`, which needed a *writable
  DuckDB* connection and so was refused outright on every natively-bound
  table — the one restriction that made raw-SQL steps unusable on exactly the
  sources plan 056 exists to serve. `RawSqlNotSupportedOnBackend` survives for
  engines with no SQL-string seam at all (Trino).
- Pivot uses `con.con.execute("CREATE OR REPLACE TEMP TABLE ... AS PIVOT ...")` — dynamic PIVOT cannot be a view in DuckDB, and `con.sql()` fails because sqlglot can't subquery a PIVOT node.

**`dte/engine/duckdb_engine.py`** — wraps `ibis.duckdb.connect()`. Exposes `con` property (the ibis backend) for use by `dlt_loader`. Only responsible for execution and output — does not load sources.

**`dte/store/`** — Protocols in `base.py`, one per persisted entity: `PipelineStore`, `SourceStore`, `DestinationStore`, `ConnectionStore`, `RunStore`. `postgres.py` is the sole production backend (SQLAlchemy async, requires `DATABASE_URL`). Tests use `tests/fakes.py` — there is no in-memory store shipped in the package. The active backend is wired in `dte/api/deps.py` and injected into routes via FastAPI `Depends()`. All four Pydantic-modelled stores speak typed SQLModel instances end-to-end (see the **Model + store pattern** subsection below); `PostgresRunStore` still hand-writes SQL because `Run` isn't a Pydantic model yet.

**`dte/api/`** — FastAPI app. Routes use `Depends(get_pipeline_store)` and `Depends(get_run_store)`. Tests override these with `app.dependency_overrides`. `_execute_pipeline` runs as an `asyncio.create_task` — trigger returns `run_id` immediately, caller polls `GET /api/runs/{run_id}`.

### Step dispatch

```python
op = step["op"]    # "filter"|"rename"|"retype"|"map"|"case"|"sort"|"aggregate"|"join"|"pivot"|"select"
                   # |"check"|"profile"|"extract"|"structure"
mode = step.get("mode")   # "lookup"|"expression"|"calculation"  — map steps only
```

`case` (if/else) compiles to `ibis.cases`, so `CaseCondition` carries
`{field, op, value, join}` rather than a SQL fragment. Two properties follow
that a SQL string would not have: the step dict *is* the editor state (no
parser, nothing lost on reopen), and `then`/`otherwise` are plain scalars,
so there is no quoting surface at all.

- **AND binds tighter than OR**, matching SQL. `_case_predicate` groups runs
  of AND before OR-ing them; a left-to-right fold would make the same rows
  mean something different in a `case` branch than in the Filter tab.
- `CaseCondition.value` is a string and `_case_value` types it — bare numbers
  and true/false at face value, everything else a string cast to the column's
  own type, so a date column compared against `"2008-01-01"` emits a real
  DATE cast instead of a lexical string comparison.
- Interpolation reaches `branches[].when[].value` explicitly; the flat
  op → top-level-field map in `_STEP_STRING_FIELDS` cannot see two levels down.

The builder's condition rows are one component, `ConditionRules` in
`components/builder/steps/editors.tsx` — shared by Filter Basic, Check Basic
and every `case` branch. Two implementations of "compose a predicate" drift,
and the drift is a quoting bug. `showSql` is off for `case`: the branch
compiles to ibis, so there is no generated SQL to preview.


### Raw SQL reaches every backend, but does not always mean the same thing

`apply_filter_sql` / `apply_expression_sql` wrap the fragment with
`table.alias(n).sql(fragment, dialect=...)`, so raw SQL runs against a
natively-bound DB source — it does not need the engine's own DuckDB
connection, which is what the old `_require_duckdb_backend` guard was really
enforcing. Reach is solved; meaning is not.

`dte/compiler/dialect_notes.py` holds what the editors render beside each
raw-SQL input (plan 062). Measured by transpiling 55 DuckDB expressions to
Postgres and running them: 51 rewrite correctly, 4 are rejected outright
(`datepart`, `contains`, `string_split`, `len(array)`), and 2 run while
meaning something else —

```
date_diff('year', dob, current_date)   dob=1990-12-31, as of 2026-08-25
    duckdb   → 36   sqlite → 36 (JULIANDAY/365.0)   postgres → 35 (AGE)
```

— plus `try_cast`, which degrades to a plain `CAST` and so raises where
DuckDB returns NULL.

- **Only that third class is curated.** The rejected ones are reported by the
  database itself, in better words than any table here would use, and
  `_DIVERGENCES` is explicitly a **measured list, not an exhaustive one** —
  which is why the UI has no affirmative "validated" state to contradict.
- **`date_diff` is worse than one unit.** `_DATE_DIFF_MEASURED` is keyed by
  `(dialect, unit)`: MySQL ignores the unit and returns whole days for all of
  them, SQLite returns days for week and quarter and divides by 30 / 365 for
  month and year. Only Postgres actually respects the unit, and disagrees with
  DuckDB about anniversaries. Any new unit offered anywhere in the UI gets
  measured before it ships.
- **Do not build this on sqlglot's static signals.** Of the four expressions
  Postgres rejects, `exp.Anonymous` catches one and
  `Generator.unsupported_messages` catches none.
- ibis transpiles a fragment **once, at `.sql()` call time**, into the table's
  own dialect and bakes it in; `ibis.to_sql(expr, dialect=…)` afterwards only
  re-renders that tree. Step SQL is therefore rendered with
  `execution_dialect_of(table)` (the ibis backend's `.name`, which doubles as
  a sqlglot dialect) — it used to use `engine.dialect`, always `"duckdb"`, so
  the SQL panel showed a query that never ran.

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

`DTE_ARTIFACT_DIR` **must** point at storage shared by the Airflow api-server
(Preview) and the task-running scheduler (Run). It defaults to the relative
`.dte-artifacts`, which resolves inside each container — they then keep
separate caches and Run re-pays for what Preview bought. Compose mounts a named
volume at `/var/lib/dte/artifacts`; `Dockerfile.airflow` creates it owned by
`airflow` so the fresh volume inherits that ownership.

**Demo/test `documents` corpora live in `backend/sample_data/`, never
`/tmp`.** `/tmp` gets swept — macOS, CI, a reboot — and a `documents` source
pointed there finds zero files with no error (it just lists nothing). Worse,
`eval_examples.doc_key` is `sha256(document bytes)`, so losing the files
orphans every label with no way to reproduce the exact bytes they were keyed
against. `backend/sample_data/eval-demo/invoices/` is committed to git,
regenerated deterministically by `backend/scripts/generate_eval_demo_invoices.py`
(built on the same `tests/fixtures/pdf_builder.build_pdf` the test suite
uses), and bind-mounted read-only into every Airflow container at
`/opt/dte/backend/sample_data`. If you add a new demo/test PDF corpus, put it here, not
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
environment, wired to every Airflow container. Do **not** put a key in the
step's `params.api_key`: step params are stored unencrypted in
`pipelines.steps` JSONB and copied into every revision. See
`plans/052-model-provider-connections.md`.

### Automap: source schema → destination schema (plan 057)

Mapping a DB→DB pipeline column by column meant guessing the destination's
column names, because nothing in the app knew them. Two additions fix that,
and neither is a new step op.

- **`GET /api/destinations/{id}/schema`** opens the destination's connection
  with `_open_ibis_backend` and returns the target table's columns in the
  *same* `InferSchemaResponse` field-tree shape sources return — one schema
  type on the frontend, not two. File targets 422: their shape is whatever
  the pipeline writes, so there is nothing to introspect.
- **`dte/automap.py`** is a pure matcher over two field lists, exposed at
  `POST /api/schema/automap`. It takes *field lists, not ids* — the builder
  already holds the source fields — so the route does no store access and no
  source loading.

Three passes, and the order is the point:

1. **exact** on the normalised name (`_norm` strips everything but
   `[a-z0-9]`, so `customer_id` == `CustomerID`).
2. **fuzzy** via `difflib.SequenceMatcher`, cutoff `0.8`, greedy best-first
   so the strongest pair claims a column before a weaker one takes it.
   stdlib — deterministic, free, and the only pass CI can run.
3. **llm** over the leftovers only, one Claude call gated on
   `ANTHROPIC_API_KEY` (`DTE_AUTOMAP_MODEL` overrides the model). Semantic
   renames (`dob` → `birth_date`) are the only reason it exists.

- **A failed model pass is `llm_error`, never a failed request.** The
  heuristic answer is still the bulk of the mapping and still worth showing.
- **The model cannot invent or steal a column**: a returned name absent from
  either input list is discarded, and a dest the heuristic already claimed
  is not overwritten. Without that guard a hallucinated column name lands as
  a `rename` that fails at write time, not at map time.
- **A type-family mismatch never rejects a match** — it attaches a warning
  (`int64 → string`) and caps confidence at `0.5`. Rejecting would hide the
  exact-name pairs people most want to review; the cap is what keeps such a
  row from being pre-ticked in the UI.

**Frontend** — `components/builder/AutoMap.tsx`, one `AutoMapButton` that
renders both the button and its portaled dialog, mounted in the *Ordered
steps* panel head on **both** step surfaces: `steps/StepsPanel.tsx` (the
new-pipeline builder) and `pipeline/steps-column.tsx` (the detail page).
Both already own `steps`/`onChange`; each gained an `outputId` prop.

- Source fields come from **`fieldsAtStep(steps.length)`**, not `allFields`.
  The generated steps append at the end, so the columns that exist *there*
  are what to map — after any earlier rename, which `allFields` would miss.
- **The proposal fires from the click that opens the dialog**, not a mount
  effect. A paid model call must not be reachable by a render.
- **Nothing is applied on arrival.** Every row is a checkbox, only
  `confidence >= 0.9` starts ticked (so a type-mismatch row never does), and
  a guessed source is editable in place. Accepting appends **one ordinary
  `select` step** — readable and editable afterwards, which is why there is
  no `automap` op and no persisted mapping. Schema drift does not
  auto-follow.
- **One `select`, never `rename` + `select`.** An `OutputField` carries an
  `alias`, so projecting and renaming are already the same step. Emitting
  both was redundant, and the rename op cannot express half of what automap
  offers anyway: `_apply_rename` validates against `table.columns`, so a
  dotted struct path (`order.amount` — what every filesystem source
  produces) raises `CompilerError`, while `_apply_output_fields` routes
  through `_resolve_field` and resolves it.

### dlt-backed writers must not normalise identifiers

`writers/postgres.py` and `writers/sql_database.py` both pass
**`naming_convention="direct"`** and a **throwaway `pipelines_dir`**. They
are a pair; neither works alone, and without them the writer silently puts
data in the wrong column.

dlt's default `snake_case` convention exists to *infer* a schema from messy
source data. Here the target table already exists with declared column
names, so the identifiers handed to dlt are the ones to write to. Under
`snake_case` a `CustomerID` column is lowercased, matches nothing, and is
**added** — the run completes, reports rows written, and leaves the column
the user actually mapped to NULL. Nothing raises. It is the worst failure
mode in this codebase and it is invisible from every surface.

- **`pipelines_dir` is why the convention alone was a no-op.** dlt persists
  a normalised schema per `pipeline_name` and the stored copy wins. These
  writers materialise the whole table each run and use no incremental
  source, so that state buys nothing — and living inside each container it
  also split between the api-server and the scheduler, the same trap
  `DTE_ARTIFACT_DIR` documents. A fresh directory per write removes both.
- **dlt also persists the convention at the destination**, in the dataset's
  `_dlt_version` / `_dlt_loads` / `_dlt_pipeline_state` tables. So a
  destination already written to under `snake_case` refuses the switch with
  `TableIdentifiersFrozen` — loud and safe, but it means **an existing
  destination fails on its next run until its `_dlt_*` tables are dropped**
  (which restarts dlt's lineage; the data tables are untouched). Its error
  text points at `schema.allow_identifier_change_on_table_with_data`, a dlt
  config key DTE exposes nowhere — dropping the `_dlt_*` tables is the
  actual remedy.
- `tests/unit/test_writer_naming_convention.py` intercepts the destination
  factory instead of connecting, which is what lets it cover snowflake and
  bigquery.

**The mysql dialect routes through dlt's `sqlalchemy` destination.** dlt
ships no mysql destination — `dlt.destinations.mysql` has never existed on
any dlt this project pins, so `dialect="mysql"` raised `AttributeError` at
write time, after the destination had saved and previewed cleanly. And the
`mysql-writer` extra said `dlt[mysql]`, which is not a real dlt extra:
`uv pip install "dlt[mysql]"` reports *"Would make no changes"*, so
installing the documented fix for MySQL support installed nothing.

`sqlalchemy` is dlt's driver layer, not a target anyone picks — the dialect
users choose stays `mysql`, and `destination_factory` is the only place the
mapping exists. Two consequences worth keeping:

- **The writer rewrites `mysql://` → `mysql+pymysql://`.** SQLAlchemy reads
  the scheme as dialect+driver and defaults bare `mysql://` to mysqldb
  (mysqlclient), which needs a C toolchain to build. Which driver we use is
  ours to pick; the URL users saved says `mysql://` because that is what the
  source side takes, and the same connection has to keep working here.
- **The image installs `[mysql-writer]`** (`dlt[sqlalchemy]` + `pymysql`,
  both pure Python). `SqlDatabaseTarget.dialect` offers mysql, so without
  them the destination saves and previews and only the write fails — the
  exact failure the `[unstructured,models]` comment above it describes.
  snowflake and bigquery stay opt-in: large SDKs, neither reachable from a
  self-hosted default.

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

