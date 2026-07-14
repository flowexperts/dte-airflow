# Plan 016 — First-class Connections (credentials layer)

## Context

Plan 015 lifted Sources and Destinations out of Pipelines into their own tables. Credentials still live inline on every Source/Destination row: an S3 source carries its HMAC key, a Postgres destination carries its connection URL. Two problems:

- **Rotation is O(rows).** Change one S3 key, edit every Source that talks to that bucket.
- **No inventory of "what infra do we talk to."** Nowhere to look up "which pipelines depend on the prod Postgres."

Introduce **Connections** as a third first-class table. A Connection holds only credentials (and connection-level metadata like region, endpoint override). Sources and Destinations reference a `connection_id` and carry only the "where inside the target" bits (bucket_url, schema/table, collection, path). Local file targets get a no-cred `local_fs` connection type so every source/dest has exactly one connection — uniform model.

Credentials are stored **encrypted at rest** in Postgres, decrypted on read via a per-process `SecretResolver` seam. This plan ships:
- The seam (`SecretResolver` protocol + factory).
- Two resolvers: `EnvSecretResolver` (preserves today's `{env: X}` behavior for dev) + `PostgresEncryptedResolver` (production default; symmetric encryption via Fernet, key from `DTE_SECRETS_KEY`).
- No external secret-manager adapters (Vault / AWS SM / GCP SM) — those slot in later as new `SecretResolver` implementations without touching loaders or writers.

## Non-goals

- Real cloud secret managers (deferred; the seam accepts them later).
- Key rotation for the Fernet key itself (would require re-encrypting all Connection rows; ship as a follow-up script if it becomes needed).
- Per-field secret refs. Whole-Connection blob only.
- Sharing / permissions. Everything visible to everyone; single-tenant.
- Versioning. Latest wins.

## Architecture

### Backend model

**`Connection`** (new, `backend/dte/models/pipeline.py`):
```python
class Connection(BaseModel):
    id: str
    connection_type: Literal[
        "local_fs", "s3", "gcs", "azure",
        "postgres", "mysql", "sqlite",
        "mongodb", "rest_api",
        "snowflake", "bigquery",
    ]
    credentials: dict  # opaque; shape depends on connection_type
    # No other required fields. Connection-level metadata (e.g. region,
    # endpoint override for S3-compatible services) lives inside `credentials`
    # because it's frequently deployment-specific and belongs with the auth.
```

**`Source`** slims down:
```python
class Source(BaseModel):
    id: str
    connection_id: str          # NEW
    source_type: str            # kept — 'filesystem'|'s3'|'sql_database'|...
    config: dict                # no creds; e.g. {bucket_url, file_glob} or {schema, table}
    table: str
```

**`Destination`** slims down parallel:
```python
class Destination(BaseModel):
    id: str
    connection_id: str          # NEW
    config: OutputTarget        # slimmed: OutputTarget variants drop cred fields
```

Each `OutputTarget` variant drops fields now supplied by the connection:
- `PostgresTarget` → drop `credentials`, keep `schema`, `table`, `write_disposition`
- `SqlDatabaseTarget` → drop `credentials`, keep `dialect`, `schema`, `table`, `write_disposition`
- `ParquetS3Target` → drop `storage_options`, keep `bucket_url`
- `JsonFileTarget` / `CsvFileTarget` → unchanged (paired with a `local_fs` connection)

Rule: `Source.source_type` / `Destination.config.type` must match the `Connection.connection_type` category. Enforced at save-time (list of compatibility rules in one dict); 422 on mismatch.

### Secret resolver seam

**`backend/dte/secrets/base.py`** (new package):
```python
class SecretResolver(Protocol):
    def encrypt(self, plaintext: dict) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> dict: ...
```

**`backend/dte/secrets/env.py`** — `EnvSecretResolver`: `encrypt` is identity (returns JSON bytes); `decrypt` walks the dict resolving `{env: "X"}` values via `os.environ`. Used when `DTE_SECRETS_BACKEND=env` (default in dev without `DTE_SECRETS_KEY`).

**`backend/dte/secrets/fernet.py`** — `FernetSecretResolver`: `cryptography.fernet.Fernet(DTE_SECRETS_KEY)`. `encrypt` serialises the dict then Fernet-encrypts; `decrypt` reverses. Used when `DTE_SECRETS_KEY` is set (production default).

**`backend/dte/secrets/__init__.py`** — `get_secret_resolver()` picks based on env (mirrors `dte.api.deps` pattern).

Loader / writer touchpoints:
- `dte/sources/loader.py` — every `_build_*_secret_sql(config, ...)` and `_load_sql_database` currently reads creds from `source.config`. Change signature to `(credentials, ...)` and pass in the resolved connection creds. `resolve_secret()` inline env-indirection stays as a per-field convenience for the `env` backend only.
- `dte/engine/writers/postgres.py`, `sql_database.py`, `parquet_s3.py` — same; receive resolved creds from the caller, don't reach into `target`.
- `dte/api/routes/pipelines.py` `_resolve()` gains a Connection lookup: for each source + destination, fetch its connection, decrypt via resolver, hand loader/writer the resolved creds.

### Store

**`ConnectionStore`** in `backend/dte/store/base.py`:
```python
class ConnectionStore(Protocol):
    async def get(self, id: str) -> dict | None: ...  # returns {id, connection_type, credentials (decrypted)}
    async def save(self, connection: dict) -> None: ...
    async def list(self, limit=50, offset=0) -> list[dict]: ...  # credentials **masked**: {**k: "***" for k in credentials}
    async def delete(self, id: str) -> bool: ...
```

Two implementations mirror the existing pattern:
- `MemoryConnectionStore` — plaintext dict (dev/test only).
- `PostgresConnectionStore` — column `credentials_encrypted bytea NOT NULL`. `save` encrypts via injected `SecretResolver`; `get` decrypts. `list` never decrypts (returns masked).

**Alembic `005_connections.py`** — creates `connections` table:
```
id                    text PK
connection_type       text NOT NULL
credentials_encrypted bytea NOT NULL
created_at            timestamptz DEFAULT now()
updated_at            timestamptz DEFAULT now()
```
Plus `sources.connection_id text NOT NULL REFERENCES connections(id) ON DELETE RESTRICT` and same on `destinations`. Migration script (below) seeds those before the FK is added.

### API

**Connections**
- `POST   /api/connections` — create. Body: `{id, connection_type, credentials}`. Encrypts + persists. 409 on id collision. Returns masked.
- `GET    /api/connections` — list. Credentials masked.
- `GET    /api/connections/{id}` — read. `?reveal=true` returns plaintext creds (defense-in-depth: log an audit line). Default masked.
- `PUT    /api/connections/{id}` — update. If `credentials` omitted, keeps existing.
- `DELETE /api/connections/{id}` — 409 with `{"referenced_by": {"sources": [...], "destinations": [...]}}` if in use.
- `POST   /api/connections/{id}/test` — attempt a lightweight connectivity check (e.g., `SELECT 1` for SQL, `HEAD bucket_url` for S3). Optional but high-value for the UI.

**Sources / Destinations** — payload gains `connection_id`; `config` shape narrows (no cred fields). Validate connection_type ↔ source/dest type compatibility on save; 422 on mismatch or missing connection.

### Frontend

- New route `/connections` — list + create + edit + delete + "Test" button. Same layout language as `/sources`.
- Connection editor: `Segmented` picker for `connection_type`, then per-type credential form:
  - `s3` — key id, secret, region, endpoint override (LocalStack).
  - `gcs` — HMAC key id, HMAC secret.
  - `azure` — tabs: connection_string | account_name+account_key.
  - `postgres` / `mysql` / `sqlite` / `snowflake` / `bigquery` — connection URL.
  - `mongodb` — connection URL.
  - `rest_api` — auth type + token / header pairs.
  - `local_fs` — no fields; just a name.
- Sidebar: **Connections** above Sources.
- `SourceEditor` gains a Connection picker at the top (dropdown of matching-type connections + "+ New connection" inline). The per-type body no longer collects creds; only `bucket_url` / `schema+table` / `collection` / etc.
- Same on `DestinationForm` and the builder's inline destination creator.
- api.ts additions: `listConnections`, `getConnection`, `createConnection`, `updateConnection`, `deleteConnection`, `testConnection`; `Connection` type.

### Migration script

**`backend/scripts/migrate_extract_connections.py`** — extracts credentials from every existing Source and Destination into new Connection rows.

For each Source:
- Compute a stable connection key from its cred fields (e.g., sorted JSON hash of `{aws_access_key_id, region_name, endpoint_url}` for S3). Same key → same Connection.
- Upsert Connection with id `conn_<source.id>` on first sighting; reuse on subsequent identical creds.
- Rewrite Source: strip cred fields from `config`, add `connection_id`.
- `filesystem` sources → auto-create a shared `local_fs_default` connection.

Same pattern for Destinations (`json_file`/`csv_file` → `local_fs_default`; others → per-cred-blob Connection).

Idempotent — running twice is a no-op.

## Reused code

- `resolve_secret()` (`backend/dte/sources/loader.py:12`) — kept, called by `EnvSecretResolver.decrypt`. Unchanged.
- Store pattern from Plan 015 (`SourceStore` / `DestinationStore` in `backend/dte/store/{base,memory,postgres}.py`) — copy for `ConnectionStore`.
- `_validate_refs` / `_resolve` pattern in `backend/dte/api/routes/pipelines.py` — extend to include connection resolution before handing creds to loaders/writers.
- The `OutputTarget` discriminated union in `backend/dte/models/pipeline.py` — narrowed (drop cred fields) not replaced.
- `SourceEditor` / `DestinationForm` / `DestinationPicker` in `frontend/src/components/builder/` — same structure, with a Connection dropdown prepended.

## Tasks (each = one worktree, one branch, one PR)

### Task 1 — Backend: secret resolver seam + Fernet resolver
- Branch: `feature/backend-secret-resolver`
- Files: `backend/dte/secrets/{__init__,base,env,fernet}.py` (new). `backend/tests/unit/test_secret_resolver.py` (new). `pyproject.toml` (add `cryptography`).
- No changes to models/routes yet — purely additive.

### Task 2 — Backend: Connection model + store + alembic + API
- Branch: `feature/backend-connections`
- Files: `backend/dte/models/pipeline.py` (add `Connection`). `backend/dte/store/{base,memory,postgres}.py` (add `ConnectionStore`). `backend/alembic/versions/005_connections.py`. `backend/dte/api/routes/connections.py`. `backend/dte/api/deps.py`. `backend/dte/api/main.py`. Tests: `test_connection_store.py`, `test_api_connections.py`.

### Task 3 — Backend: rewire loaders + writers to take resolved creds; update Source/Destination models
- Branch: `feature/backend-rewire-creds`
- Files: `backend/dte/sources/loader.py` — extract cred args from every `_load_*` and `_build_*_secret_sql`. `backend/dte/engine/writers/{postgres,sql_database,parquet_s3}.py` — same. `backend/dte/models/pipeline.py` — add `Source.connection_id`, `Destination.connection_id`; narrow `OutputTarget` variants. `backend/dte/api/routes/pipelines.py` — resolve connection per source/destination in `_resolve`. Validate type compatibility on save. Update all tests.

### Task 4 — Backend: `POST /api/connections/{id}/test`
- Branch: `feature/backend-connection-test`
- Files: `backend/dte/api/routes/connections.py`. `backend/dte/sources/connection_test.py` (new) — per-type probe functions. `backend/tests/unit/test_connection_test.py`.

### Task 5 — Backend: migration script
- Branch: `feature/backend-migrate-connections`
- Files: `backend/scripts/migrate_extract_connections.py` (new). `backend/tests/unit/test_migrate_extract_connections.py` (new).

### Task 6 — Frontend: `/connections` page + Connection editor per type
- Branch: `feature/frontend-connections-page`
- Files: `frontend/src/app/(app)/connections/{page,new,[id]/edit}.tsx` (new). `frontend/src/components/connection-form.tsx`, `connections-table.tsx` (new). Per-type sub-editors under `frontend/src/components/connections/{S3ConnectionEditor,PostgresConnectionEditor,...}.tsx`. `frontend/src/lib/api.ts` — connection helpers + `Connection` type. Sidebar entry.

### Task 7 — Frontend: SourceEditor + DestinationForm gain Connection picker
- Branch: `feature/frontend-source-dest-connection-picker`
- Files: `frontend/src/components/builder/sources/SourceEditor.tsx` — prepend Connection dropdown, drop cred inputs from per-kind editors. `frontend/src/components/builder/sources/{FilesystemSourceEditor,SqlSourceEditor,MongoSourceEditor}.tsx` — remove cred fields, keep bucket/table/collection. `frontend/src/components/destination-form.tsx` — same shape. `frontend/src/components/builder/DestinationPicker.tsx` — inline creator gets the picker too. `frontend/src/components/builder/schema-context.tsx` — no change (still uses source id).

### Task 8 — Docs
- Branch: `feature/docs-connections`
- Files: `CLAUDE.md` — new "Connections" subsection covering the three-tier model (Connection → Source/Destination → Pipeline), the secret resolver seam, `DTE_SECRETS_KEY` env var, `local_fs` special case, testing endpoint.

## Verification

1. `cd backend && uv run pytest -x` — all green.
2. Fresh Postgres: `alembic upgrade head` creates `connections`, adds `connection_id` FKs on `sources`/`destinations`.
3. `DTE_SECRETS_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")` set on backend.
4. `POST /api/connections` with an S3 cred body → 201; `GET /api/connections/{id}` shows masked creds; `?reveal=true` shows plaintext.
5. `POST /api/connections/{id}/test` against a live LocalStack → `{"ok": true, "elapsed_ms": …}`.
6. `POST /api/sources` referencing the connection id, with only `bucket_url` + `file_glob` in config → 201.
7. `POST /api/pipelines` referencing that source + a `local_fs` destination → 201; trigger → run completes; loader received resolved creds without them ever appearing in the Source row.
8. `DELETE /api/connections/{id}` while a Source references it → 409 with `referenced_by`.
9. Pre-load a plan-015-shape pipeline (embedded creds in `Source.config`), run `python scripts/migrate_extract_connections.py --write`, verify one Connection row created per unique cred blob, Source/Destination rows now carry `connection_id` and cred-free `config`.
10. In the UI: `/connections` list + create + edit + delete + Test. Source editor Connection dropdown filters by connection_type. Deleting an in-use connection surfaces the referencing sources/destinations in the error.

## Breaking changes

- Every existing Source and Destination gets a required `connection_id`. Clients POSTing the plan-015 shape (creds inside config) → 422. Migrate first (Task 5), then deploy.
- Backend now needs `DTE_SECRETS_KEY` in prod. Missing → falls back to `EnvSecretResolver` with a startup warning (so dev without Postgres still works).
- `OutputTarget` union variants change shape (drop cred fields). Any external caller building `PostgresTarget` / `SqlDatabaseTarget` / `ParquetS3Target` payloads directly needs updating.

## Sequencing

Land Plan 015 to `main` first (already done in worktree `worktrees/first-class-endpoints`; needs merge). Then start Plan 016 in a fresh worktree stacked on `main`.
