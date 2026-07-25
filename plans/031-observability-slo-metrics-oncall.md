# Plan 031 — Observability: SLO/SLI + Prometheus RED metrics + on-call runbook

Covers P3 #28, #29, #30 from `plans/027-p0-p4-status-ladder.md`. Bundled because each depends on the others: SLOs need metrics to measure against, runbooks need SLOs to define "abnormal".

Current state: OpenTelemetry spans opt-in (`dte/tracing.py`), structured logging with `request_id_var` + `run_id_var` (`dte/logging.py`), `/healthz` + `/readyz` shipped. No metrics endpoint, no dashboards, no runbook.

## SLO catalog (P3 #28)

Four SLOs. Each has SLI definition, measurement source, target, and error budget.

### 1. Pipeline run success rate

- **SLI**: `runs where status='completed' or status='completed_with_warnings' / all runs where status != 'cancelled'` over rolling 30 days.
- **Target**: **99.5%** — i.e. 5 failures per 1000 non-cancelled runs.
- **Error budget**: 43 minutes of "runs failing at 100%" per 30 days (0.5% × 30d × 24h × 60m).
- **Alert**: burn > 2× budget over 6 h → page. Burn > 10× over 1 h → page.

### 2. Pipeline run p95 duration (bounded to < 1M rows)

- **SLI**: `histogram_quantile(0.95, sum by (le) (rate(dte_pipeline_run_duration_seconds_bucket{rows_bucket="lt_1m"}[30d])))`.
- **Target**: **< 60 s**.
- **Rationale**: preview and small runs must feel interactive. Bigger runs get their own SLO once we're onboarded to a customer whose volumes justify it.

### 3. HTTP API availability

- **SLI**: `1 - (5xx / total)` for `/api/*` excluding `/api/pipelines/*/trigger` (async endpoints return 202 immediately; failures happen out-of-band and are covered by SLO #1).
- **Target**: **99.9%** over 30 days.
- **Error budget**: 43 minutes / 30 days.

### 4. API p95 latency

- **SLI**: `histogram_quantile(0.95, http_request_duration_seconds_bucket{route!~"/api/pipelines/.+/preview"})`.
- **Target**: **< 300 ms**.
- **Exclusion**: preview is compute-heavy and has its own separate observation.

Stored in `docs/observability/slos.md`; alerts codified in `observability/prometheus/rules.yml` (grafana repo can rehost).

## Metrics inventory (P3 #30)

Use `prometheus-fastapi-instrumentator>=7.0,<8.0` as the RED-metrics baseline. Adds ~50 KB.

### HTTP (auto-instrumented)

- `http_requests_total{method,route,status}` — counter
- `http_request_duration_seconds{method,route}` — histogram, default buckets

### Domain metrics (hand-instrumented in `_execute_pipeline`)

- `dte_pipeline_runs_total{status}` — counter incremented on terminal status
- `dte_pipeline_run_duration_seconds{source_type}` — histogram, buckets `[0.5, 1, 2, 5, 10, 30, 60, 300, 900, 3600]`
- `dte_source_load_duration_seconds{source_type}` — histogram, same buckets
- `dte_rows_written_total{destination_type}` — counter, incremented by `rows_written` per successful run
- `dte_compile_duration_seconds` — histogram
- `dte_active_runs` — gauge, incremented on trigger / decremented on terminal
- `dte_pool_hits_total{pool}` — counter (from plan 028)

### Endpoint

`GET /metrics` under `dte/api/routes/metrics.py`. No auth (Prom scrape). CORS-blocked. Bind under `app.include_router(metrics.router)` before `mount_admin`.

### Dashboard

Grafana JSON stubs at `observability/dashboards/dte-red.json` and `observability/dashboards/dte-runs.json`. Panels:

- **RED page**: request rate, error rate %, p50/p95/p99 latency per route.
- **Runs page**: runs/min by status, success rate, p50/p95 duration by source_type, active runs, rows written per hour.

## On-call runbook (P3 #29)

Top-5 failure modes lifted from real prior incidents plus the observability surface:

### Runbook index (`docs/runbooks/oncall/README.md`)

1. `pipeline-stuck-running.md` — a run's status has been `running` for > 3× its p95. Cancel via `POST /api/runs/{id}/cancel`; if it doesn't transition, kill the backend pod, look for stuck DuckDB / dlt state.
2. `postgres-unreachable.md` — `/readyz` returning 503. Check `docker compose ps postgres`, `docker compose logs postgres --tail=50`, connection count via `SELECT count(*) FROM pg_stat_activity`.
3. `duckdb-oom.md` — run failed with `Out of Memory Error`. Check the source's row count vs the container's memory limit (`deploy.resources.limits.memory` from plan P1 #18). Lower `settings.run_max_rows` for the offending pipeline until source can be filtered upstream.
4. `source-auth-spike.md` — `dte_pipeline_runs_total{status="failed"}` spike correlated with a single `source_type`. Likely a rotated credential or vendor auth outage. Check the source's Connection, run `POST /api/connections/{id}/test`.
5. `fernet-key-mismatch.md` — after a rotation, `decrypt` fails. Roll back to the previous key, re-run rotation from a fresh dump, see `docs/runbooks/secrets-rotation.md`.

Each runbook ~30 lines: symptom, first three checks (with copy-pasteable commands), mitigation, escalation trigger.

## Task list

- `feature/prom-metrics` — instrumentator, `/metrics` route, domain metrics in `_execute_pipeline`.
- `feature/slo-defs` — `docs/observability/slos.md`, `observability/prometheus/rules.yml`, dashboard JSONs.
- `docs/oncall-runbooks` — five runbook files + README.
- `feature/oncall-dry-run` — a chaos-lite script that triggers each failure mode against a staging stack to verify runbook steps work.

## Cost

- Prometheus scrape footprint: 15-second scrape × ~40 series = trivial.
- Grafana: assume an existing tenant on the ops platform, not new spend.
- Dev time: ~5 days across the four branches.

## Rollout

- Ship metrics **dark**: scrape endpoint live, no dashboards published, no alerts.
- One week of baseline collection.
- Publish dashboards + SLOs; alerts start firing.
- Two more weeks tuning alert thresholds; then declare SLOs "committed".

## Non-goals

- Distributed tracing propagation across services (single service today).
- Log aggregation platform (assume ops-standard Loki/Splunk).
- Anomaly detection / ML-driven alerting.
