# Plan 028 — Connection pooling (Mongo / dlt / DuckDB)

Covers P2 #22 from `plans/027-p0-p4-status-ladder.md`.

## Problem

Every pipeline run today constructs fresh clients:

- **Mongo** (`dte/sources/loader.py`, `mongodb` branch): new `MongoClient(url)` per run. TCP + auth handshake per invocation; server sees churn on the connection-count metric.
- **dlt** (`mongodb`, `rest_api`): `dlt.pipeline(...)` reinit per run — walks the state dir, re-derives the destination, opens a fresh DuckDB attach for its internal book-keeping.
- **DuckDB scanner extensions** (`sql_database`, `s3`, `gcs`, `azure`): `INSTALL … ; LOAD … ; ATTACH … ; CREATE VIEW …` on every run, even though the DuckDB session and extensions do not change.

Fine for demos and preview requests. Under a customer running 20 pipelines every 5 minutes the wasted setup cost becomes measurable: Mongo Atlas alone throttles new-connection storms after ~100/s per cluster.

## Design

Per-source-type pool, all keyed on the **Connection.id** (never on user-editable configs), all with explicit eviction on connection update.

### Mongo

New module `dte/sources/pools/mongo.py`:

```python
_clients: dict[str, MongoClient] = {}
_lock = asyncio.Lock()

async def get_mongo_client(conn: Connection) -> MongoClient:
    async with _lock:
        client = _clients.get(conn.id)
        if client is None:
            client = MongoClient(conn.credentials["url"], appname="dte")
            _clients[conn.id] = client
        return client

async def evict(conn_id: str) -> None:
    async with _lock:
        client = _clients.pop(conn_id, None)
    if client is not None:
        client.close()
```

Called from `PUT /api/connections/{id}` and `DELETE /api/connections/{id}` in `dte/api/routes/connections.py`.

### dlt

`dlt.pipeline` is heavier — carries filesystem state under `~/.dlt/`. Cache the pipeline object per `(source_id, destination_id)` pair, not per connection, because dlt binds source+dest at pipeline construction. Same lock+dict pattern.

Eviction hooks: source update, destination update, connection update transitively via source/dest lookup.

### DuckDB scanner extensions

`DuckDBEngine.__init__` today calls `ibis.duckdb.connect()` — creates a fresh DuckDB per run. Move to **process-wide singleton** guarded by an `asyncio.Lock`:

```python
_engine: DuckDBEngine | None = None

async def get_engine() -> DuckDBEngine:
    global _engine
    if _engine is None:
        _engine = DuckDBEngine()
        # Extensions are per-DB, so this only happens once per process:
        for ext in ("httpfs", "azure", "sqlite", "postgres_scanner", "mysql", "excel"):
            _engine.con.raw_sql(f"INSTALL {ext}; LOAD {ext};")
    return _engine
```

`CREATE OR REPLACE VIEW` per source still runs — that's cheap and unavoidable because view definitions depend on the run's source config. What we save is the DuckDB startup cost + extension INSTALL round-trips.

### Preview endpoint

Preview shares the engine and pools. Since preview is short-lived and read-only, no lock contention concern.

## Lifecycle

- **Creation**: lazy on first use. No eager warming at app start.
- **Eviction**: connection PUT/DELETE evicts by id; source PUT evicts dependent dlt pipelines.
- **TTL**: none. Long-lived clients are fine; DuckDB is single-process-scoped.
- **Shutdown**: `app.on_event("shutdown")` closes all Mongo clients.

## Thread + async safety

- All pools guarded by `asyncio.Lock`.
- Pymongo `MongoClient` is thread-safe; we hand it out under lock but callers use it freely.
- DuckDB connection is single-threaded — we already access it through ibis's `.con` which serialises internally. Long queries (compilation, execute-to-json) run inside a single event loop under our current model.

## Feature flag

`DTE_CONNECTION_POOL_ENABLED` — default `false` in v1. Flip to `true` after a week of dogfooding under Docker Compose. Delete the flag two releases later.

## Testing

- Unit test each pool module: two consecutive `get_x(conn)` calls return the same object; `evict` drops the entry; `evict` on an unknown id is a no-op.
- Integration: two triggers of the same pipeline within 60 s produce runs whose `Mongo.appname` metadata shows the same connection id.
- Load test: 50 runs in a tight loop with pool on vs off; measure delta on `pipeline_run_duration_seconds`.

## Migration

None — behaviour change only. No schema, no data.

## Task list

- `feature/pool-engine-singleton` — `DuckDBEngine` singleton + extension preload. Touches `dte/engine/duckdb_engine.py`, `dte/api/routes/pipelines.py` (preview + trigger).
- `feature/pool-mongo` — new module `dte/sources/pools/mongo.py`, wire eviction in `dte/api/routes/connections.py`.
- `feature/pool-dlt` — new module `dte/sources/pools/dlt.py`, wire eviction on source + destination + connection updates.
- `feature/pool-flag-and-metrics` — flip `DTE_CONNECTION_POOL_ENABLED` in staging, emit `dte_pool_hits_total{pool}` counter.

## Non-goals

- Cross-process pooling (would need Redis or dedicated pool server).
- Connection health probing / auto-reconnect — clients already handle transient failures.
- Query-result caching. Different concern (P4 territory).
