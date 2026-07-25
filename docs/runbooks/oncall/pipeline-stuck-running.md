# Runbook: pipeline stuck in `running`

**Symptom**: A run's status has been `running` for > 3× the pipeline's p95 duration. Frontend `Timeline` shows no progress. `dte_active_runs` stays elevated.

## First checks

1. Grab the run id from the UI or `GET /api/pipelines/{id}/runs?limit=5`.
2. Look at the most recent per-step event:
   ```
   GET /api/runs/{run_id}/events
   ```
   If events stop at a specific step, that's the culprit stage.
3. Check backend logs filtered by `run_id`:
   ```
   docker compose logs backend --since 15m | jq 'select(.run_id=="<id>")'
   ```

## Mitigation

- **Cancel the run**:
  ```
  POST /api/runs/{run_id}/cancel
  ```
- If the run doesn't transition within 30 s the local task registry (`dte.runs`) can't reach it — likely the process was restarted. Force-mark as failed via the store's admin path.
- Restart the backend pod as last resort. Runs in flight are already lost.

## Root-cause hunts

- **DuckDB deadlock** — very rare, but check with `ATTACH ... AS x; PRAGMA memory_limit;` and thread counts. Usually surfaces as CPU pegged with no I/O.
- **dlt state directory grew unbounded** — `~/.dlt/pipelines/*` can accumulate. Purge, restart pod.
- **Source hang** — Mongo replica-set failover, S3 throttle, upstream API 5xx. Check `dte_source_load_duration_seconds` histogram for the source type.

## Escalation

If mitigation fails inside 15 min and the run belongs to a paying customer, escalate to platform lead and post in `#dte-incident`.
