# DTE on-call runbook index

Top failure modes and where to look first. Keep runbooks under ~40 lines each —
they should be scannable at 3am. Update whenever an incident retro surfaces a
new failure or a stale mitigation.

| # | Symptom | Runbook |
| - | - | - |
| 1 | A run's status stuck at `running` for > 3× p95 | [pipeline-stuck-running.md](pipeline-stuck-running.md) |
| 2 | `/readyz` returning 503 | [postgres-unreachable.md](postgres-unreachable.md) |
| 3 | Run fails with `Out of Memory Error` from DuckDB | [duckdb-oom.md](duckdb-oom.md) |
| 4 | Spike in `dte_pipeline_runs_total{status="failed"}` on one source_type | [source-auth-spike.md](source-auth-spike.md) |

## First response for anything

1. Check `/healthz` and `/readyz` on the affected environment.
2. Check current SLO burn on the Grafana runs dashboard.
3. Grep the last 15 minutes of structured logs for `ERROR` or `credential_decrypt` spikes.
4. Ask in `#dte-oncall` before making customer-visible changes.
