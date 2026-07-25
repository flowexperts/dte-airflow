# Runbook: source-auth failure spike

**Symptom**: `dte_pipeline_runs_total{status="failed"}` sharply increases, and the failure error strings all reference the same `source_type` (403, 401, or auth-related). Frequently caused by rotated credentials or vendor outage.

## First checks

1. Group failures by source_type in Grafana or Prom:
   ```
   sum by (source_type) (rate(dte_pipeline_runs_total{status="failed"}[15m]))
   ```
2. Identify the affected Connection ids from the failing runs' error messages.
3. Probe the connection:
   ```
   POST /api/connections/{id}/test
   ```
   → returns `{ok, elapsed_ms, detail}`. Look at `detail` for the exact error.
4. Check the vendor status page (AWS, Mongo Atlas, etc.).

## Mitigation

- **Rotated credentials**: PUT the affected Connection with the new credentials. Runs auto-recover on next trigger.
- **Vendor outage**: pause the affected pipelines by setting `active: false` (or DELETE + revert once vendor recovers). Post ETA in `#dte-oncall`.
- **Networking**: verify egress from the backend pod — often a firewall rule change upstream.

## Root-cause hunts

- Cross-reference the spike start with the audit log (`event=credential_decrypt` on `dte.audit.credentials`) to see when the affected Connection was last successfully used.
- If the credential is env-indirected (`{env: "X"}`), verify the underlying env var didn't clear.

## Escalation

If the spike involves > 1 tenant's shared connection type (e.g. all S3 sources), escalate immediately — either our IAM role changed or the vendor is having a regional issue.
