# Scenario test suite — real services, real API, one flow per step op

## Context

Today DTE's test suite is fast but shallow: unit tests hit a `TestClient` wired to `Fake*Store` instances (`tests/fakes.py`), and the one integration test (`tests/integration/test_execution.py`) only exercises the filesystem source with local JSON fixtures. There's no coverage that a real user's flow — pick a source in a real database, wire connections, save a pipeline, trigger it, download the output — actually works end-to-end. When we add source kinds or change the API surface, the first person who finds out it broke is the user.

This plan builds a **scenario suite** that drives the running backend over HTTP like a user would: one scenario per step op, plus one per source kind, against real containers (Postgres, MySQL, MinIO, MongoDB, SFTP, etc.). It also adds a new `sftp` source kind since the user wants FTP/SFTP coverage and DTE has no such source today.

## Approach

### 1. New source kind: `sftp`

Before scenarios can exercise SFTP, add the source itself.

- `dte/models/pipeline.py`:
  - Extend `SourceKind` with `"sftp"`.
  - Extend `ConnectionType` with `"sftp"`.
  - Add `SftpSourceConfig(bucket_url: str, file_glob: str = "**/*.json")` following `FilesystemSourceConfig` shape.
  - Add `_SftpCredSpec` (host, port, username, password, private_key) into `_DLT_CRED_CLASS` — hand-rolled dataclass, not a dlt spec (dlt has no first-class SFTP creds).
  - Extend `SOURCE_CONNECTION_COMPAT`: `"sftp": {"sftp"}`.
- `dte/sources/loader.py`: add `_load_sftp` that mirrors the S3 loader — install DuckDB `httpfs`? No — DuckDB has no SFTP reader. Instead: use `paramiko` (already indirectly available via dlt) to `SFTPClient.get()` matching files into a temp dir, then load them the same way `filesystem` does (`read_json_auto` on the local temp path). Cleanup temp dir in a `finally`. Keep it simple; a single glob walk.
- `dte/sources/connection_test.py`: `_test_sftp` — open a `paramiko.Transport`, auth, list root, close. Return `elapsed_ms`.
- Frontend: not in scope for this plan — add later.

### 2. Docker stack for scenarios

New file: **`docker-compose.scenarios.yml`** (sibling to root `docker-compose.yml`, extends it):

| Service | Image | Purpose |
|---|---|---|
| `scenario-postgres` | `postgres:16` | source + destination (separate DB from app's postgres) |
| `scenario-mysql` | `mysql:8` | sql_database source with mysql dialect |
| `scenario-mongo` | `mongo:7` | mongodb source |
| `scenario-minio` | `minio/minio` | S3-compatible (endpoint_url override) |
| `scenario-sftp` | `atmoz/sftp` | SFTP source, seeded volume with fixture files |
| `scenario-restapi` | `wiremock/wiremock` | rest_api source, JSON responses served from mounted mappings |

All bound to fixed high ports (55432, 53306, 57017, 59000, 52222, 58080). One shared docker network. Backend and app-postgres from the existing compose keep running normally — scenarios stack is additive.

`Makefile` targets: `make scenarios-up`, `make scenarios-down`, `make scenarios-reset` (down + volumes prune + up).

### 3. Suite layout

```
backend/tests/scenarios/
  conftest.py                # http client fixture, per-scenario cleanup, service readiness gates
  fixtures/
    orders.json              # canonical small dataset (~20 rows)
    products.json            # for join/lookup scenarios
    customers.json           # for pivot/aggregate scenarios
    orders.csv               # for csv variants
    seed_postgres.sql        # loaded into scenario-postgres on startup
    seed_mysql.sql
    seed_mongo.js
    wiremock_mappings/       # mounted into scenario-restapi
  helpers.py                 # user-flow helpers (see §4)
  steps/                     # one file per step op
    test_filter.py
    test_rename.py
    test_retype.py
    test_map_lookup.py
    test_map_expression.py
    test_sort.py
    test_aggregate.py
    test_join.py
    test_pivot.py
    test_select.py
  sources/                   # one file per source kind
    test_source_filesystem.py
    test_source_postgres.py
    test_source_mysql.py
    test_source_mongodb.py
    test_source_s3_minio.py
    test_source_sftp.py
    test_source_restapi.py
  destinations/
    test_dest_json_file.py
    test_dest_csv_file.py
    test_dest_postgres.py
  combined/
    test_end_to_end_orders.py   # sql source → filter → aggregate → csv dest
    test_end_to_end_multi.py    # two sources → join → select → json dest
```

Marker: `pytest.mark.scenario` registered in `pyproject.toml`. `pyproject.toml` also excludes `tests/scenarios/` from the default run (opt-in via `-m scenario` or explicit path) so CI stays fast.

### 4. `helpers.py` — the user-flow DSL

Thin wrappers over `httpx.Client(base_url=os.environ["DTE_API_URL"])`. Each helper mirrors one user action; scenarios read like a script.

```python
def create_connection(client, *, id, type, credentials) -> dict
def create_source(client, *, id, source_type, connection_id, config, table=None, format=None) -> dict
def create_destination(client, *, id, dest_type, connection_id, config) -> dict
def create_pipeline(client, *, id, sources, steps, output_id) -> dict
def trigger_and_wait(client, pipeline_id, timeout=30) -> dict  # polls /api/runs/{id}
def read_output(client, run_id, limit=100) -> list[dict]
def cleanup(client, ids_by_kind)                   # DELETE everything in reverse order
```

Every scenario is roughly:

```python
def test_filter_keeps_only_matching_rows(client, scenario_ids):
    src = create_source(client, id=scenario_ids("src"), source_type="filesystem", ...)
    dst = create_destination(client, id=scenario_ids("dst"), dest_type="json_file", ...)
    pipe = create_pipeline(client, id=scenario_ids("pipe"), sources=[src["id"]],
        steps=[{"op": "filter", "expr": "amount > 100"}], output_id=dst["id"])
    run = trigger_and_wait(client, pipe["id"])
    assert run["status"] == "completed"
    rows = read_output(client, run["id"])
    assert {r["order_id"] for r in rows} == {"o2", "o5", "o7"}
```

`scenario_ids` is a per-test fixture that generates unique IDs (e.g. `f"scenario_{uuid4().hex[:8]}_src"`) so parallel runs and reruns don't collide, and pushes them onto a stack that the teardown fixture flushes via `cleanup()`.

### 5. Data conventions

Small, hand-crafted, deterministic:
- `orders.json`: 20 rows, columns `order_id, customer_id, product_id, amount, status, ordered_at`.
- `products.json`: 5 rows, `product_id, name, category, unit_price`.
- `customers.json`: 6 rows, `customer_id, name, region`.
- Assertions are exact (row sets or full ordered lists) — deterministic data is the whole point.
- Same JSON gets seeded into Postgres/MySQL/Mongo/MinIO/SFTP by the container init scripts, so the same scenario logic works across sources by only swapping the source id.

### 6. Readiness + isolation

- `conftest.py`'s session fixture waits for `GET /health` on the backend and probes each scenario container's port with a socket connect (retry up to 30s). Skips scenario file if its service isn't reachable — so a dev without MySQL up can still run the filesystem scenarios.
- Each test creates its own connection/source/destination/pipeline IDs (uuid-suffixed) and cleans up in `finally`, so test order doesn't matter and reruns are safe.
- Postgres destinations write to a per-test schema; teardown drops the schema.

### 7. What we're **not** doing

- No BigQuery/Snowflake/Azure — no cheap local emulators worth the complexity.
- No frontend scenarios; this is API-level user simulation.
- No CI wiring in this plan (add later once the suite is stable — it needs the scenario stack up).

## Critical files

**New**
- `docker-compose.scenarios.yml`
- `backend/tests/scenarios/` (whole tree above)
- `backend/dte/sources/` — SFTP loader additions

**Modified**
- `backend/dte/models/pipeline.py` — SourceKind, ConnectionType, `SftpSourceConfig`, `_DLT_CRED_CLASS`, `SOURCE_CONNECTION_COMPAT`
- `backend/dte/sources/loader.py` — dispatch for `sftp`
- `backend/dte/sources/connection_test.py` — `_test_sftp`
- `backend/pyproject.toml` — register `scenario` marker, exclude `tests/scenarios/` from default collection, add `paramiko` dep
- `Makefile` (or add one) — `scenarios-{up,down,reset}` targets

## Reuse

- `tests/fakes.py` pattern is **not** reused — scenarios talk to the real API + real stores.
- `httpx` is already a backend dep (dlt pulls it in) — no new HTTP client dep.
- Existing `TestClient`-based tests keep running unchanged; scenarios live in a separate directory with a separate marker.
- The compiler-level assertions in `tests/unit/test_compiler.py` stay — scenarios are additive, not a replacement.

## Verification

```bash
# 1. Bring up the scenario stack
docker compose -f docker-compose.yml -f docker-compose.scenarios.yml up -d --build

# 2. Wait until backend is healthy on :8001
curl -f http://localhost:8001/health

# 3. Run all scenarios
cd backend && uv run pytest tests/scenarios -m scenario -v

# 4. Run one op in isolation
cd backend && uv run pytest tests/scenarios/steps/test_join.py -v

# 5. Run only source coverage
cd backend && uv run pytest tests/scenarios/sources -v

# 6. Confirm the default test run still works and is fast
cd backend && uv run pytest        # should skip tests/scenarios/ entirely
```

Success = every scenario finishes green, `run["status"] == "completed"`, and the output rows match the hand-crafted expected sets exactly. If MySQL isn't up, its scenarios auto-skip (not fail) so a dev can run a subset.
