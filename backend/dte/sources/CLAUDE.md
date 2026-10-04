## Connections (three-tier model)

Sources and destinations reference a **Connection** by `connection_id`. A Connection holds only credentials (opaque encrypted blob). Sources / destinations hold only the "where inside the target" bits (bucket_url, schema+table, collection, path). Local file targets bind to a no-cred `local_fs` connection so every source and destination has exactly one connection to point at.

Three tiers:

```
Connection (credentials)
    ↑
Source / Destination (references connection_id + carries kind-specific config)
    ↑
Pipeline (references source ids + destination id)
```

### Credential validation via dlt's `@configspec` classes

`Connection.credentials` is validated at model-parse time by instantiating the matching dlt spec class (`dlt.common.configuration.specs.AwsCredentials`, `ConnectionStringCredentials`, etc). We do NOT inherit — that would drag in dlt's config-provider machinery. Instead we call the class, extract public fields via `dataclasses.fields()`, drop dlt's built-in defaults and Nones, and store the result as an opaque dict. See `_DLT_CRED_CLASS` in `dte/models/pipeline.py`.

**Rule for adding a new integration**: add the connection type to `ConnectionType`, add the dlt cred class to `_DLT_CRED_CLASS`, and (for SQL-family) route through `ConnectionStringCredentials` — dlt destinations accept the resulting URL directly.

`ConnectionString`-family (postgres/mysql/sqlite/snowflake/bigquery/mongodb) collapses to `{"url": "..."}` on store — same shape dlt destinations accept.

### Secret resolver seam

`dte/secrets/` — pluggable resolver interface. Two shipped:
- **EnvSecretResolver** (default in dev): stores plaintext JSON; resolves `{env: "X"}` values from `os.environ` at decrypt time. Preserves the plan-014 env-indirection UX.
- **FernetSecretResolver** (prod): symmetric encryption via `cryptography.fernet.Fernet`. Key from `DTE_SECRETS_KEY` env var (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).

`get_secret_resolver()` in `dte/secrets/__init__.py` picks:
1. `DTE_SECRETS_BACKEND=env|fernet` — explicit override.
2. `DTE_SECRETS_KEY` set → Fernet.
3. else → Env resolver, with a startup warning if `DATABASE_URL` is also set (prod signal).

External adapters (Vault, AWS SM, GCP SM) plug in as new resolvers without touching loaders or writers.

### Connection type ↔ Source/Destination compatibility

Enforced in the API save layer (`SOURCE_CONNECTION_COMPAT` / `DESTINATION_CONNECTION_COMPAT` maps in `dte/models/pipeline.py`). Mismatched combinations (e.g. an s3 source bound to a postgres connection) → 422 on POST/PUT.

### Test endpoint

`POST /dte/api/connections/{id}/test` — lightweight connectivity probe. Returns `{ok: bool, elapsed_ms: int, detail: str}`. Per-type probes in `dte/sources/connection_test.py`. UI shows the result inline on `/connections`.

### Migration

Legacy plan-015 sources/destinations (creds inline in `config`) migrate via `backend/scripts/migrate_extract_connections.py`. Extracts unique cred blobs into Connection rows (sha1-deduped), rewrites source/dest configs to reference by id. `filesystem`/`json_file`/`csv_file` all share a singleton `local_fs_default` connection. Idempotent.

## First-class sources and destinations

Sources and destinations are stored independently of pipelines. Pipelines reference sources by table ref, not bare id: `Pipeline.sources: list[SourceTableRef]` and `Pipeline.output_id: str`. Both sides get their own store protocol (`SourceStore`, `DestinationStore` in `backend/dte/store/base.py`), memory + Postgres implementations, and CRUD API routes.

- `Source` (renamed from `DltSource`) — `id`, `source_type`, `config`, `table`, `format`. `DltSource` remains as a deprecated alias for one release. `format` is a top-level nullable column (migration `009`) — one of `json`/`jsonl`/`ndjson`/`csv`/`parquet`/`excel`, or NULL for auto-detect from the glob extension. Only meaningful for filesystem-family kinds. On save, `Source` rejects `format` that lives in a different reader family than the glob's trailing extension (e.g. `format=excel` + `*.csv` → 422); same-family mismatches like `format=jsonl` + `*.json` pass through, preserving the "wrong extension, right content" escape hatch.
- `Destination` — `{id, config: OutputTarget}` where `OutputTarget` is the existing discriminated union (`json_file` | `csv_file` | `excel_file` | `parquet_s3` | `postgres` | `sql_database`). File-shaped targets (`json_file`, `csv_file`, `excel_file`, `parquet_s3`) enforce that the on-disk extension matches the target family — a `json_file` at `orders.csv` is rejected at save (422), same for missing extensions. `.jsonl`/`.ndjson` are accepted for `json_file` (same family). Non-file destinations (`postgres`, `sql_database`) are unaffected.
- Pipeline execution (`preview`, `trigger`) resolves each source ref's `source_id` via `SourceStore.get` and the destination id via `DestinationStore.get` before compiling. Missing id → 422 naming what's missing.
- `compile_pipeline(pipeline, tables, output=None)` — the compiler is source-agnostic; the caller passes the resolved `OutputTarget` if it needs the output-fields projection.
- Legacy embedded pipelines migrate via `backend/scripts/migrate_embedded_endpoints.py`: extracts every embedded `Source` and `output` into their own tables (generated dest id: `<pipeline_id>_output`), rewrites the pipeline. Idempotent.
- Module rename: `dte.sources.dlt_loader` → `dte.sources.loader`. A `dlt_loader` shim re-exports for one release.
- Alembic `004` creates the `sources` and `destinations` tables. Shape: `id text PK`, `source_type`/`dest_type text`, `config jsonb`, plus `table_name` on sources.

### DB sources are database-scoped; tables are picked per pipeline (plan 056)

A `sql_database` Source used to bind to exactly one physical table
(`SqlDatabaseSourceConfig.table`), so joining three tables out of one
Postgres database needed three Source rows, each hand-typed. `Source.config`
now holds only the schema/database — no table — and the table is a
per-pipeline decision:

```python
class SourceTableRef(BaseModel):
    source_id: str
    table: str | None = None   # required for sql_database, forbidden otherwise
    alias: str                 # the compiler registry key. Required, unique.
```

- **`alias` is the registry key, and it is explicit** — never
  `f"{source_id}::{table}"`. A composite string can't be split back apart
  reliably (quoted identifiers may contain `::`), collapses two refs to the
  same source+table into one dict entry (silent duplicate loss), and forces
  a sentinel for non-DB sources that have no table. A user-chosen alias also
  makes self-joins (`orders o1 JOIN orders o2`) expressible again, where
  collapsing to one-source-one-table had removed them.
- **`alias` is required on the wire, never defaulted server-side** —
  defaulting it needs a store lookup inside a Pydantic validator (sync, no
  DB access, not implementable). The builder fills it in when a table is
  picked (`orders`, then `orders_2` on collision); the backend only
  validates: unique within the pipeline, non-empty,
  `^[A-Za-z_][A-Za-z0-9_]*$`.
- `table` is required when the resolved source is `sql_database`, and must
  be absent for every other kind. `JoinStep.left`/`.right` must resolve to a
  declared alias or an earlier step's `output_id` — checked at save
  (`_validate_pipeline_refs` in `dte/api/routes/pipelines.py`) as a 422
  naming the bad operand, not a `KeyError` 500 inside the compiler.
- `load_source(source, registry, connection, credentials, table=None)` —
  `table` threads only to `_load_sql_database`, which uses it instead of
  `config["table"]`. Every other loader ignores it. `Source.table` (the
  top-level DB column) is unrelated and untouched — it's the DuckDB view
  name for filesystem/mongodb/rest_api/documents sources, not a physical
  table reference, and stays `NOT NULL`.
- **Introspection** opens a native, connection-id-cached ibis backend
  (`_open_ibis_backend`), not a DuckDB `ATTACH`: `GET
  /api/connections/{id}/schemas` (`connection:read`) lists schemas/databases
  via `backend.list_databases()`; `GET /api/sources/{id}/tables`
  (`source:read`) lists tables via `backend.list_tables(database=...)`. Both
  422 for connection/source kinds with no native backend, and surface a
  cold/unreachable connection's driver-timeout as a 422 with the driver's
  message rather than hanging the picker.
- `POST /api/schema/infer` and `GET /api/sources/{id}/schema` take a
  `?table=` query param — a table-less `sql_database` source can't load, so
  schema inference 422s without it. `SchemaProvider` is keyed by `alias`, not
  `source_id`, so a two-table pipeline off one source gets two distinct
  field sets instead of one overwriting the other.
- Compiler registry is keyed by `ref.alias`; `current_key` seeds from
  `pipeline.sources[0].alias`.
- **Migration `037` is a clean break, not a lossy auto-conversion**: every
  `pipelines` and `pipeline_revisions` row is deleted outright (a bare
  source id carries no table name to backfill). `runs.pipeline_id`'s FK has
  no cascade (unlike `runs.revision_id`, which has `ON DELETE SET NULL` from
  migration `014`), so the migration drops `runs_pipeline_id_fkey` first —
  historical runs survive as orphaned rows pointing at pipeline ids that no
  longer resolve. Run-detail tolerates a missing pipeline rather than 500.

