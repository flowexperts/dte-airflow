# Runbook: DuckDB OOM during a pipeline run

**Symptom**: Run fails with `Out of Memory Error` from DuckDB. `dte.access` logs show the exception at the compile or execute stage. Backend container memory limit hit.

## First checks

1. Which source_type is loading? `dte_source_load_duration_seconds` histogram will show the outlier.
2. What are the row counts?
   ```
   POST /api/pipelines/{id}/preview?limit=1
   ```
   → then eyeball how many source rows would land in the join.
3. What's the container's memory limit? `docker compose config | grep -A2 resources` — set by plan P1 #18 (`2G` on backend by default).

## Mitigation

- **Immediate**: cancel the offending run (`POST /api/runs/{run_id}/cancel`).
- **Check the DuckDB cap.** Each connection is limited to `DTE_DUCKDB_MEMORY_LIMIT` (default `2GB`) and spills to `DTE_DUCKDB_TEMP_DIR` (default `<tmp>/dte-duckdb`). An OOM under the cap usually means the temp dir's disk is full or the worker runs more concurrent runs than (worker memory ÷ cap). An empty `DTE_DUCKDB_MEMORY_LIMIT` restores DuckDB's 80%-of-RAM default per connection, which is what OOM-kills workers.
- **Lower `settings.run_max_rows`** for the pipeline so the guardrail trips before OOM.
- **Add a `filter` step early** in the pipeline to shrink the intermediate.
- **Bump the memory limit** in `docker-compose.yml` under `services.backend.deploy.resources.limits.memory` (last resort; also bumps every pipeline's peak).

## Root-cause hunts

- **Cross join** — check for a `join` step with a bad `key` producing NxM output.
- **Unbounded `map` expression** — DuckDB materialises intermediate arrays; a `map` expanding one row into many can spike memory.
- **STRUCT explosion** on filesystem sources with deeply nested JSON — the schema-infer path will show the depth.

## Escalation

Repeated OOMs on the same pipeline → root-cause and land a filter fix. Repeated OOMs across pipelines → memory limit is too tight for the workload; capacity plan.
