# Plan 074: Connections come from installed Airflow providers

Worktree: `worktrees/pip-install` (branch `feature/pip-install`), same as plan 073.
The repo copy goes to `plans/074-provider-connections.md`.

## Context

DTE is becoming a pip-installable Airflow plugin (plan 073). Today it hand-maps
Airflow connections in `dte/airflow/connections.py`:
- S3, GCS and Azure: `login`/`password`/extras are copied into DuckDB `CREATE SECRET`
  (`dte/sources/duckdb_secrets.py`).
- SQL databases: DTE builds the URL itself.

Problems with that:
- **Most real auth modes fail.** AWS IAM role, assume-role and profiles; Azure
  service principal and managed identity; GCP service-account JSON (DuckDB only takes
  HMAC keys for GCS). These are what production Airflow uses.
- **DTE offers kinds the deployment can't serve.** It shows mongo, mssql and sqlite
  regardless of whether a provider for them is installed. The stock
  `apache/airflow:3.3.2` image has none of the three.
- **Connections DTE can't see.** It reads connections from the metadata-DB rows only,
  so `AIRFLOW_CONN_*` variables and secrets backends are invisible.

**The deal (user's words):** whatever Airflow provider is installed, DTE supports
that connection. The provider does the auth and DTE doesn't re-implement it.

**Decisions made:**
- **Object storage** goes through Airflow's `ObjectStoragePath(url, conn_id=…)`. That
  gives an fsspec filesystem built by the provider, which DuckDB reads and writes via
  `register_filesystem`.
- **SQL** goes through the provider hook's SQLAlchemy URL.

## Step 0: Triage (before any change)

On Airflow 3.3.2's pinned versions, the scenario tier gives **68 failed / 47 passed**.
Run the same tier on `uv.lock` versions to separate failures that were already there
from ones the version bump caused. Then fix the ones the bump caused in DTE, per the
saved rule: DTE fits Airflow's pins, not the other way round. Also run the
integration tier against `dte-it-pg` (port 55432, still running).

## Design

### 1. Provider-backed resolver: `dte/airflow/connections.py` (rewrite)

- `get_connection(conn_id)`: use `BaseHook.get_connection`, which covers DB rows,
  env vars and secrets backends, then `conn.get_hook()`.
- A table maps Airflow `conn_type` to a DTE kind and a resolver. Keep the existing
  `Connection.connection_type` values so saved sources/destinations still validate
  (`SOURCE_CONNECTION_COMPAT` in `dte/models/pipeline.py`).

| conn_type | DTE kind | credentials (what DTE stores in memory) |
|---|---|---|
| `aws` | `s3` | `{"conn_id"}`: storage is resolved lazily through ObjectStoragePath |
| `google_cloud_platform` | `gcs`, or `bigquery` (existing `dte_type` extra) | gcs: `{"conn_id"}`; bigquery: `{"url": hook URL}` |
| `wasb`, `adls`, `azure_data_lake` | `azure` | `{"conn_id"}` |
| `sftp` | `sftp` (new; same storage path) | `{"conn_id"}` |
| `fs` | `local_fs` | `{}` (unchanged) |
| `postgres`, `mysql`, `mssql`, `sqlite`, `snowflake` | unchanged | `{"url": hook.sqlalchemy_url}` (fallback `hook.get_uri()`), rendered with the password |
| `mongo` | `mongodb` | `{"url": MongoHook(conn_id).uri}` |
| `http` | `rest_api` | unchanged mapping (HttpHook auth is request-time; keep the current dict) |

- **Gating:** a kind is available only if `ProvidersManager().hooks` has its
  `conn_type`. Storage kinds also need the scheme in
  `ProvidersManager().filesystem_module_names`.
- Unmapped or unavailable types are skipped. That's the existing `ValueError` path in
  `connection_store._rows`.
- **SQL URL normalisation:** `sqlalchemy_url` may carry a driver suffix
  (`postgresql+psycopg2`, `mysql+mysqldb`). `dte/engine/backend_registry.py`
  `_open_*` parses with `urlparse`, so strip or translate the driver there in one
  helper, the way `dte/airflow/db.py` `_PG` does.

### 2. Connection store: `dte/airflow/connection_store.py`

- `get` goes through the resolver above. Secrets backends and env vars now work.
- `list` keeps the DB rows and adds env-var connections (`AIRFLOW_CONN_*`, parsed with
  `Connection.from_json`/URI). Secrets backends can't be listed; the docs say so.
- Both filter to available kinds.

### 3. Object storage through provider filesystems: `dte/sources/object_store.py` (new)

- One helper, `register(raw_con, url, conn_id) -> duckdb_url`:
  1. `fs = ObjectStoragePath(url, conn_id=conn_id).fs`
  2. Give each connection its own protocol, `dte_<scheme>_<conn_id>`, so two S3
     connections in one pipeline don't collide. DuckDB keys registered filesystems by
     protocol.
  3. `raw_con.register_filesystem(fs)`
  4. Return the URL rewritten to that protocol.
- **Reads:** `_load_s3`, `_load_gcs`, `_load_azure` and a new `_load_sftp` in
  `dte/sources/loader.py` collapse into one `_load_object_store` that calls
  `register`, then reuses the existing `_duckdb_reader_call` and view creation. Don't
  load `httpfs`/`azure` for these.
- **Writes:** `dte/engine/writers/_copy.py` `prepare_object_store` uses the same
  `register` for remote destinations, so `COPY … TO` lands through the provider
  filesystem.
- The `documents` source (local-only today) can use the same helper later; out of
  scope here.
- **Delete:** the s3/gcs/azure secret builders and the `_SCHEME_BACKEND` /
  `_SECRET_BUILDER` routing in `dte/sources/duckdb_secrets.py`, plus their unit tests.
  Keep `_ensure_ext`/home-dir handling for the format extensions (excel).
- **Risks to verify first (spike, about 30 minutes):**
  - DuckDB `register_filesystem` with a renamed protocol, for both `read_parquet`
    glob and `COPY TO`.
  - The fsspec glob semantics for `**`.
  - If the protocol rename doesn't work, fall back to one DuckDB connection per
    storage connection id. `BackendRegistry` already keys backends by connection id.

### 4. Connectivity test: `dte/sources/connection_test.py`

- Prefer the provider's own `hook.test_connection()` where the hook defines it.
- Storage: `ObjectStoragePath(bucket, conn_id).exists()` or a one-entry `ls`.
- Delete the per-type probes this replaces.

### 5. What the UI offers

- New `GET /dte/api/capabilities` (in `dte/api/routes/connections.py`). It returns the
  available source kinds and destination types, with, for each unavailable one, the
  provider package to install (e.g. `apache-airflow-providers-mongo`).
- Frontend: `src/components/builder/sources/types.ts` `SOURCE_KINDS` and
  `src/components/destination-form.tsx`. Unavailable kinds render disabled, with an
  "install <package>" hint. Add `sftp` to both kind lists and compat maps (front and
  back).
- Regenerate `src/lib/api-types.ts` with `scripts/gen-api-types.sh`.

### 6. Dependencies (`backend/pyproject.toml`)

- **Drop DTE extras the providers already cover:** `s3` (s3fs), the `azure-storage-blob`
  and `s3fs` dev entries, and the `bigquery-source`/`snowflake-source` ibis extras stay
  only if ibis needs them beyond the provider.
- **Add provider-aligned extras that only name providers:** `amazon =
  ["apache-airflow-providers-amazon[s3fs]"]`, `mongo =
  ["apache-airflow-providers-mongo"]`, `mssql =
  ["apache-airflow-providers-microsoft-mssql", ...existing]`. No version ceilings
  (plan 073 rule). The stock image lacks s3fs, so S3 needs the amazon extra.
- `Dockerfile.airflow`: install with `[amazon,mongo,mssql,…]` so the Compose stack
  keeps every kind.

### 7. Carry-over from plan 073 (unfinished)

- Install doc and `scripts/test-pip-install.sh` use Airflow's constraints
  **unmodified** (drop the `grep -v sqlglot`).
- `uv lock`; README quickstart; `.github/workflows/release.yml`; switch the site
  quickstart in `feature/site-oss` to the pip install.

## Tests (TDD, failing first)

- **Unit** (no Airflow; fake `get_connection`/hook objects, like `tests/airflow/test_connections.py`):
  - The mapping table: conn_type to kind; SQL URL taken from a fake hook's
    `sqlalchemy_url`; storage conns yield `{"conn_id"}`.
  - Gating: a fake `ProvidersManager` without mongo hides `mongodb`.
  - `object_store.register` protocol rewrite, using a `fsspec` `memory://` filesystem
    with real DuckDB. This proves read and `COPY TO` through a registered filesystem
    without Airflow.
  - The capabilities route.
- **Airflow tier** (extend `scripts/test-pip-install.sh`, stock image + emulators):
  - MinIO (an `aws` connection with an `endpoint_url` extra), Azurite (`wasb`) and
    fake-gcs-server (`google_cloud_platform`), each read through a pipeline.
  - A Parquet write to MinIO.
  - The connection defined only as `AIRFLOW_CONN_*`, to prove env-var connections
    resolve.
  - With the mongo provider absent, `/dte/api/capabilities` reports mongodb as
    unavailable.
- Rework `scripts/test-cloud-storage.sh` / `tests/integration` cloud tests to
  build Airflow connections, or fold them into the Airflow tier above.

## Verification

1. `cd backend && .venv/bin/python -m pytest -q` (unit), then the scenario and
   integration tiers on Airflow's pinned versions. Compare against the Step 0 baseline.
2. `scripts/test-pip-install.sh` prints `PASS`.
3. `docker compose up -d --build` from this worktree. In the UI, create an S3 source
   on an `aws` connection that has no keys (IAM/env credentials via MinIO env vars)
   and run it. Kinds without providers show disabled with the install hint.

## Files

- **Rewrite:** `backend/dte/airflow/{connections,connection_store}.py`, `backend/dte/sources/connection_test.py`.
- **New:** `backend/dte/sources/object_store.py`, `plans/074-provider-connections.md`.
- **Edit:**
  - backend: `backend/dte/sources/{loader,duckdb_secrets}.py`, `backend/dte/engine/writers/_copy.py`,
    `backend/dte/engine/backend_registry.py`, `backend/dte/models/pipeline.py` (sftp kind + compat),
    `backend/dte/api/routes/connections.py`, `backend/pyproject.toml`
  - frontend: `frontend/src/components/builder/sources/types.ts`,
    `frontend/src/components/destination-form.tsx`, `frontend/src/lib/api-types.ts`
  - Docker and scripts: `Dockerfile.airflow`, `scripts/test-pip-install.sh`
  - docs: `docs/user/self-hosting/install-plugin.md`, `docs/user/connections/index.md`, README
- **Delete:** the s3/gcs/azure secret builders and their unit tests.

## Follow-up (done in the same branch)

- `apache-airflow>=3.3`, no ceiling: DTE installs on any 3.3+ with that release's constraints.
- BigQuery: the google provider's `gcpbigquery` type maps to `bigquery`; reads pass
  `GoogleBaseHook.get_credentials()` to ibis, writes pass them to dlt when dlt can take
  them natively (service account, OAuth), else dlt's default credentials.
- Probe of the stock 3.3.2 image: every SQL driver DTE reads and writes with ships
  with it; only `s3fs` (amazon extra) and `sshfs` (sftp extra) are missing.
- Smoke tier adds fake-gcs-server (anonymous gcp conn + `gcs.endpoint`), an SFTP
  server, and Postgres -> Postgres through the postgres provider hook.
- Docs, README and the site quickstart now lead with the pip install.
