# Plan 034 — Distributed execution seam (Trino MVP)

Covers P2 #25 from `plans/027-p0-p4-status-ladder.md`.

## Current state

`DuckDBEngine` (`backend/dte/engine/duckdb_engine.py`) is the sole execution backend. It wraps `ibis.duckdb.connect()` and exposes `.con` for the loader. The compiler (`backend/dte/compiler/ibis_compiler.py`) speaks ibis end-to-end **except** for two raw-SQL escape hatches:

1. **Filter Advanced tab** — user-supplied DuckDB SQL string, passed through `con.create_view()` + `con.sql()`.
2. **Expression map / calculation** — evaluates a user expression via the same mechanism.

Every source loader is DuckDB-specific too: `filesystem` uses `read_json_auto`, `sql_database` uses `postgres_scanner` etc., `s3` uses `httpfs`.

## Second backend — pick

| Candidate | Pro | Con |
| - | - | - |
| **Trino** | Query lakes/warehouses in place; no data movement. Ibis has mature Trino support. Federated joins across S3 + Postgres out-of-the-box. | Requires a Trino cluster (customer or hosted). Advanced-tab SQL breaks (Trino SQL ≠ DuckDB SQL). |
| Spark | Best for wide/big transformations. Cluster elasticity. | Startup latency (~30 s per session) kills preview UX. Adds JVM to the ops surface. |
| Polars / Datafusion | Single-node, closer to DuckDB perf profile. | Doesn't buy us "reach customer's data lake" — same locality as DuckDB. |

**Recommendation: Trino as the second engine.** Payoff is "connect DTE to a customer's Trino/Iceberg and never move a byte" — a real differentiator versus dbt.

Spark can wait until a customer forces it.

## Target abstraction

New protocol `dte/engine/base.py`:

```python
class Engine(Protocol):
    """Minimum surface a compilation backend must expose."""

    ibis_backend: BaseBackend      # so the compiler stays ibis-native

    def read_source_view(self, source: Source, view_name: str) -> ibis.Table:
        """Materialise a source as a named view/table in the backend."""

    def raw_sql_view(self, name: str, sql: str) -> ibis.Table:
        """Register a raw-SQL view — used by Filter/Advanced and expression map."""

    def execute_to_writer(
        self, table: ibis.Table, target: OutputTarget
    ) -> int:
        """Run + write; return rows_written."""

    def close(self) -> None: ...
```

`DuckDBEngine` implements this — small refactor, no behaviour change.

`TrinoEngine` new implementation:
- Config: `catalog`, `schema`, `host`, port, user, auth. Sourced from a new `trino` `Connection` type.
- `read_source_view` maps `filesystem` and `s3` sources onto existing Iceberg / Hive catalogs (source config carries `catalog` + `schema` + `table` for the Trino case). No `sql_database` path for MVP.
- `raw_sql_view` accepts SQL only if the pipeline has been marked `engine: "trino"`.

## Pipeline dispatch

`Pipeline.engine: Literal["duckdb", "trino"] = "duckdb"`. Compile-time dispatch:

```python
engine = get_engine(pipeline.engine)
table = compile_pipeline(pipeline, tables={src.id: engine.read_source_view(src, src.id) for src in sources})
rows = engine.execute_to_writer(table, output)
```

Engine registry `dte/engine/__init__.py` holds `{"duckdb": DuckDBEngine, "trino": TrinoEngine}`. Trino registration is behind `DTE_TRINO_ENABLED`.

## Raw-SQL portability

Two options:

- **(a) Declare non-portable — reject Advanced SQL and expression map when `engine=trino`.** Simplest. UI adds "This pipeline runs on Trino; Advanced SQL is disabled" hint. Users who want portability stick to Basic filter + typed step ops.
- (b) Translate via `sqlglot` — parse DuckDB SQL, emit Trino SQL. Works for many cases, fails silently for others.
- (c) Portable expression AST — build our own IR. Weeks of work; not worth it before customer demand.

**MVP: option (a).** Ship (b) later if customers ask.

## Testing

- Reuse the scenario suite, matrix `engine=duckdb` (default) and `engine=trino` under a new pytest marker `trino` — skipped unless `DTE_TRINO_TEST_URL` is set.
- Testcontainers-python spins up a Trino image (`trinodb/trino:latest`) for CI (opt-in, expensive).
- All existing DuckDB scenarios remain gated to `engine=duckdb` — they exercise the Advanced tab, which Trino rejects.

## Compat notes

- Ibis `ibis-framework[trino]` optional-extra in `pyproject.toml`.
- The compiler already threads through the engine's ibis backend — no compiler rewrite.
- Preview endpoint stays DuckDB-only for now; Trino preview costs are unpredictable.

## Task list

- `feature/engine-protocol` — extract `Engine` Protocol, refactor `DuckDBEngine` to implement it.
- `feature/trino-engine` — new `TrinoEngine`, `trino` Connection type, dispatch.
- `feature/engine-dispatch-ui` — `Pipeline.engine` field, builder UI, "Advanced disabled" hint.
- `feature/trino-scenarios` — testcontainer scenario tier.

## Rollout

- Ship `Engine` Protocol without exposing user-facing choice (feature-flagged).
- Ship `TrinoEngine` behind `DTE_TRINO_ENABLED=false`.
- Design partner customer flips the flag; iterate on real data before general availability.

## Non-goals

- Cluster orchestration for the Trino side (Kubernetes deployment templates, autoscaling).
- Automatic engine selection based on data size (heuristic dispatch — nice-to-have but manual is fine).
- Cross-engine result caching.
