# DTE Service-Level Objectives

Four SLOs, each with SLI definition, measurement source, target, and burn-rate
alerts. See `plans/031-observability-slo-metrics-oncall.md` for the design
rationale.

Measurement window unless otherwise noted: **rolling 30 days**.

---

## SLO 1 — Pipeline run success rate

- **SLI**: fraction of `dte_pipeline_runs_total` where `status="completed"` (or `status="completed_with_warnings"` once data-quality contracts ship) divided by non-cancelled terminal runs.
- **Prom expression**:
  ```
  sum(rate(dte_pipeline_runs_total{status=~"completed|completed_with_warnings"}[30d]))
    / sum(rate(dte_pipeline_runs_total{status!="cancelled"}[30d]))
  ```
- **Target**: **99.5%**.
- **Error budget**: 0.5% × (30d × 24h × 60m) = **43 minutes** at 100% failure per 30d.
- **Burn alerts**:
  - Page: 2× burn over 6 h.
  - Page: 10× burn over 1 h (fast-burn).

## SLO 2 — Pipeline run p95 duration (< 1M rows)

- **SLI**: p95 of `dte_pipeline_run_duration_seconds` for runs whose `rows_written` is under 1M. Bucketed labels TBD when we track that dimension.
- **Prom expression**:
  ```
  histogram_quantile(0.95, sum by (le) (
    rate(dte_pipeline_run_duration_seconds_bucket[30d])
  ))
  ```
- **Target**: **< 60 s**.
- **Rationale**: preview and small runs must feel interactive. Larger workloads earn their own SLO once a customer's volume justifies it.

## SLO 3 — HTTP API availability

- **SLI**: `1 - (5xx responses / total responses)` over `/api/*` excluding `/api/pipelines/*/trigger`.
- **Prom expression**:
  ```
  1 - (
    sum(rate(http_requests_total{route=~"/api/.*", status=~"5.."}[30d]))
      / sum(rate(http_requests_total{route=~"/api/.*"}[30d]))
  )
  ```
- **Target**: **99.9%**.
- **Exclusion**: async trigger endpoint returns 202 immediately — pipeline failures happen out-of-band and are captured by SLO 1.

## SLO 4 — HTTP API p95 latency

- **SLI**: p95 of `http_request_duration_seconds` on all `/api/*` except preview.
- **Prom expression**:
  ```
  histogram_quantile(0.95, sum by (le) (
    rate(http_request_duration_seconds_bucket{route!~"/api/pipelines/.+/preview"}[30d])
  ))
  ```
- **Target**: **< 300 ms**.
- **Exclusion**: preview is compute-heavy and has its own observation.

---

## Error-budget policy

- When any SLO consumes > 50% of its 30-day budget, non-critical feature merges pause until the burn recovers.
- When any SLO exhausts its budget, only fixes for the offending failure mode ship.
- Weekly SLO review in the platform on-call handoff; monthly report to stakeholders.

## Dashboards

- `observability/dashboards/dte-red.json` — HTTP request rate, errors, latency per route.
- `observability/dashboards/dte-runs.json` — runs/min by status, success rate, p50/p95 duration, active runs.

Grafana JSON is scaffolded but not yet populated — populate when the ops platform is wired up.
