# Data flow

What actually happens when a pipeline runs.

## The shape

```
Source config(s)
    │
    ▼
loader → ibis.Table per source
    │  (via dlt for mongodb / rest_api; via DuckDB extensions for everything else)
    ▼
compile_pipeline(steps, tables) → single ibis.Table
    │
    ▼
DuckDB executes → destination writer
    │
    ▼
Output file or table + rows_written
```

## Loading

`dte/sources/loader.py` — one function per source kind:

- **filesystem** — `CREATE OR REPLACE VIEW … AS SELECT * FROM read_json_auto(…)` (also `read_csv_auto`, `read_parquet`, `read_xlsx`). Format inferred from the glob extension; `config["format"]` overrides.
- **s3 / gcs / azure** — install the matching DuckDB extension, `CREATE OR REPLACE SECRET`, then the same `read_*` call against the remote URL.
- **sql_database** — install the scanner extension (`sqlite_scanner`, `postgres_scanner`, `mysql_scanner`), `ATTACH … READ_ONLY`, expose the table as a view.
- **mongodb / rest_api** — dlt `@dlt.resource` / `rest_api_source`, materialised into DuckDB.

All sources end up as `ibis.Table` objects bound to a single shared DuckDB connection for the run.

## Compiling

`dte/compiler/ibis_compiler.py` — `compile_pipeline(pipeline, tables)` walks the ordered step list. Each step reads from and writes back to a **named registry** (`dict[str, ibis.Table]`), keyed by `current_key`.

- Most ops are direct ibis calls (`.filter`, `.mutate`, `.group_by`, `.order_by`, `.select`).
- **Filter (Advanced)** and **Map · expression** escape to raw SQL via `con.create_view(...)` + `con.sql(...)`. ibis has no SQL string parser.
- **Pivot** uses `con.con.execute("CREATE OR REPLACE TEMP TABLE … AS PIVOT …")` — dynamic PIVOT can't be a view in DuckDB, and sqlglot can't subquery a PIVOT node.
- **Join** writes its result under `output_id` and updates `current_key`. Later steps read from `output_id` explicitly. This is how multi-source pipelines work.

Field references use dot syntax. `_resolve_field()` splits on `.` and traverses struct members; if the head isn't a top-level column it falls back to the joined `__` name (dlt-flattened columns from mongodb / rest_api).

## Executing + writing

`dte/engine/duckdb_engine.py` — wraps `ibis.duckdb.connect()`. Executes the compiled expression, then hands the result to the destination writer under `dte/engine/writers/` (`json_file.py`, `csv_file.py`, `parquet_s3.py`, `postgres.py`, `sql_database.py`, `excel_file.py`).

Writers pull credentials from the destination's linked Connection at write time — dlt destinations accept the URL/dict form directly.

## Runs

- Trigger → `POST /api/pipelines/{id}/trigger` → creates a `run` row (status `pending`), returns `{run_id}` immediately.
- Execution runs as `asyncio.create_task(...)`. The route does not block on it.
- Status transitions: `pending → running → completed | failed`.
- `finished_at` is stamped by a `BEFORE UPDATE` trigger on the `runs` table (migration `003`). API code does not set it — a new terminal status has to be added to both the trigger and the memory-store shim.

## Store layer

Every persisted entity (pipeline, source, destination, connection, lookup table) is a two-class pair in `dte/models/pipeline.py`: a `XxxBase(SQLModel)` for API/domain, and a `Xxx(XxxBase, table=True)` for persistence. Stores live under `dte/store/`; `postgres.py` is the sole production backend. Tests use fakes from `tests/fakes.py`.

## Further reading

- `plans/` — numbered feature plans, each documents the reasoning behind one shipped change.
- `ARCHITECTURE.md` — the exhaustive contributor reference.
- `CLAUDE.md` — code-navigation guide for the whole repo.
