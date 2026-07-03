# Plan 000 — Original Architecture (Phase 1)

## What was built

DTE Phase 1: a batch data transformation engine with a Python backend and REST API. No UI yet. All state is in-memory.

## Data flow

```
Pipeline JSON
    ↓
Pipeline (Pydantic model)
    ↓
DuckDBEngine.load_json() / load_csv()  →  ibis.Table (per source)
    ↓
compile_pipeline(pipeline, tables)     →  ibis.Table (transformed)
    ↓
DuckDBEngine.execute_to_json()         →  output JSON file
```

## Pipeline JSON spec

A pipeline has three sections: sources, steps, output.

```json
{
  "id": "p1",
  "name": "my pipeline",
  "sources": [
    {"id": "s1", "type": "json_file", "path": "/tmp/data.json"}
  ],
  "steps": [
    {"op": "filter", "expr": "amount > 100"},
    {"op": "rename", "mappings": {"first_name": "name"}},
    {"op": "retype", "field": "age", "to_type": "int"},
    {"op": "map", "mode": "lookup", "field": "country", "table": {"US": "United States"}},
    {"op": "map", "mode": "expression", "output_field": "total", "expr": "price * quantity"},
    {"op": "sort", "by": ["amount"], "ascending": false},
    {"op": "aggregate", "group_by": ["category"], "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}]}
  ],
  "output": {"type": "json_file", "path": "/tmp/out.json", "fields": []}
}
```

`Pipeline.steps` is `list[dict]` not a typed Union because the `map` op needs a sub-discriminator on `mode` that Pydantic's discriminated union can't handle with a shared `op` key. The compiler parses each dict by `op` + `mode`.

## Source types (Phase 1)

| type | model | what it does |
|---|---|---|
| `json_file` | `JsonFileSource` | local JSON file, loaded via `DuckDBEngine.load_json()` |
| `csv_file` | `CsvFileSource` | local CSV file, loaded via `DuckDBEngine.load_csv()` |
| `postgres` | `PostgresSource` | Postgres table — model exists, loader not yet implemented |

Sources are discriminated by `type` field in Pydantic. `DuckDBEngine` uses DuckDB's `read_json` / `read_csv` which auto-detects nested JSON schemas and loads them as struct columns.

## Step types

| op | model | ibis strategy |
|---|---|---|
| `filter` | `FilterStep(expr)` | `create_view` + `con.sql("SELECT * FROM v WHERE {expr}")` — Ibis has no SQL string parser |
| `rename` | `RenameStep(mappings)` | `table.rename({new: old})` — note Ibis rename direction |
| `retype` | `RetypeStep(field, to_type)` | `table.cast({field: ibis_type})` |
| `map/lookup` | `LookupMapStep(field, table, default)` | `ibis.cases(*[(col==k, v),...], else_=default)` via `table.mutate()` |
| `map/expression` | `ExpressionMapStep(output_field, expr)` | `create_view` + `con.sql("SELECT *, ({expr}) AS {field} FROM v")` |
| `map/calculation` | same model as expression | same — calculation is an alias for expression |
| `sort` | `SortStep(by, ascending)` | `table.order_by([ibis.asc/desc(col), ...])` |
| `aggregate` | `AggregateStep(group_by, aggregations)` | `table.group_by(...).aggregate(...)` |

Filter and expression map are the only steps that escape to raw SQL. This is the intended seam where future distributed backends (Spark, Trino) would plug in different SQL dialects.

## Dot-notation field resolution

DuckDB's `read_json` loads `{"order": {"amount": 100}}` as a struct column `order` with sub-field `amount`. The compiler's `_resolve_field(table, "order.amount")` splits on `.` and traverses struct fields via `col[part]`. This applies to `group_by`, `sort.by`, and `aggregate.field` — anywhere a step config references a field by name.

## Engine

`DuckDBEngine` holds a single `ibis.duckdb.connect()` connection. All source loads and view creation share this connection. The compiler's `_find_backend()` call on an ibis table reaches back to this same connection — that's how filter/expression steps register views and query them.

## API (Phase 1, in-memory)

```
POST   /api/pipelines              store pipeline dict, return {id}
GET    /api/pipelines/{id}         return pipeline dict
POST   /api/pipelines/{id}/trigger asyncio.create_task → return {run_id}
GET    /api/runs/{run_id}          return {status, error, rows_written}
```

State lives in two module-level dicts on `dte/api/main.py`:
- `_pipelines: dict[str, dict]`
- `_runs: dict[str, dict]`  — each run: `{status, error, rows_written, pipeline_id}`

Routes import these dicts directly from `main` (not via dependency injection) to avoid circular imports. Execution status values: `pending` → `running` → `completed` / `failed`.

## Output (Phase 1)

Only `json_file` output is implemented. `DuckDBEngine.execute_to_json()` calls `table.execute()` to get a pandas DataFrame, converts to `list[dict]`, writes as JSON. `output.fields` applies a final column selection + alias before execution.

## File layout

```
dte/
├── models/pipeline.py       # Pydantic spec — sources, steps, output
├── schema/inferrer.py       # JSON schema inference (dot-notation, type merging)
├── compiler/ibis_compiler.py # Pipeline → ibis.Table expression chain
├── engine/
│   ├── base.py              # BaseEngine ABC
│   └── duckdb_engine.py     # DuckDB backend
├── connectors/              # Hand-rolled source adapters (to be replaced by dlt)
│   ├── base.py
│   └── json_connector.py
└── api/
    ├── main.py              # FastAPI app + in-memory stores
    └── routes/
        ├── pipelines.py     # CRUD + trigger
        └── runs.py          # Run status

tests/
├── unit/
│   ├── test_pipeline_spec.py    # 11 tests
│   ├── test_schema_inferrer.py  # 9 tests
│   └── test_compiler.py         # 11 tests
└── integration/
    └── test_execution.py        # 3 end-to-end tests
```

## Known limitations going into Phase 2

- `connectors/` is hand-rolled and cannot handle S3, MongoDB, or any cloud source — replaced by dlt in plan 001
- Joins are not implemented (Phase 2)
- Pivot is not implemented (Phase 2)
- No persistent store — pipelines and run history lost on restart
- Only JSON file output — no DB write target
- Schema inferrer operates independently of DuckDB's own schema detection; these should be unified
- No UI
