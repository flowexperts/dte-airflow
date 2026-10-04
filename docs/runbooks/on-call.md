# DTE on-call runbook

> **Outdated since plan 065.** DTE now runs inside Airflow: there is no `backend`/`worker` service, job queue or `DTE_JOB_QUEUE_ENABLED`. Runs are Airflow dag runs — debug them in the Airflow UI (task logs) and `docker compose logs airflow-scheduler`. Sections below that mention workers or procrastinate no longer apply.

2am document. Terse, imperative. Assume the reader has never opened this repo.

---

## Purpose + escalation

DTE is a batch data-transformation platform: FastAPI backend (uvicorn on `:8001`), Postgres 16 (metadata + runs), Next.js frontend (`:3000`), DuckDB for execution.

**Check which execution mode this deployment is in before anything else** — the failure modes below differ:

```bash
docker compose exec backend printenv DTE_JOB_QUEUE_ENABLED
```

- **Unset / `false` (default)** — pipelines run as `asyncio.create_task` inside the backend process, single-worker uvicorn. Cancel only works on the process that started the run.
- **`true` (distributed)** — `POST /trigger` enqueues a Postgres-backed procrastinate job; separate `dte-worker` processes (`python -m dte.worker`) execute it. Cancel is queue-native and works across replicas.

Neither mode distributes a *single* run — DuckDB is single-node either way.

Owners:

| Area                              | Owner            |
| --------------------------------- | ---------------- |
| Backend / compiler / runs         | Platform         |
| Postgres, migrations              | Platform         |
| Frontend                          | Product-eng      |
| Connections / customer creds      | Platform + SRE   |

Escalation ladder:

1. **On-call primary** — pager, first responder.
2. **On-call secondary** — 15 min no-ack from primary.
3. **Platform lead** — >30 min unresolved P0/P1, or blast radius > single tenant.
4. **Head of Eng** — customer-visible outage > 1 hour, or data loss suspected.

Page (P0/P1) vs defer (P2):

- **Page** — `/readyz` red > 3 min, error rate > 5% for 5 min, any run reporting `data loss`, customer creds leaked/mis-decrypted.
- **Defer to next business day** — single pipeline failing due to user config, single stuck run you already cancelled, non-blocking migration warning, dashboard gaps.

---

## Health checks

```bash
# Liveness (process up)
curl -fsS http://<host>:8001/healthz
# → {"status":"ok"}

# Readiness (Postgres round-trip)
curl -fsS http://<host>:8001/readyz
# → {"status":"ready"}
# fail →  {"status":"not_ready","detail":"<sqlalchemy error>"}
```

- `healthz` returning non-200 → uvicorn wedged or container dead. Restart backend.
- `readyz` returning `not_ready` → Postgres unreachable, pool exhausted, or credentials broken. See failure mode #2.

Docker healthcheck (backend container runs `urllib.request` against `/healthz` every 10s):

```bash
docker compose ps                                          # STATUS column shows (healthy)/(unhealthy)
docker inspect --format='{{json .State.Health}}' dte-backend-1 | jq
# → { "Status": "healthy|unhealthy", "Log": [ {ExitCode, Output, Start, End} ... ] }
```

External probe from outside the cluster (bastion / laptop):

```bash
curl -m 5 -o /dev/null -w '%{http_code} %{time_total}s\n' https://<public-host>/healthz
```

---

## Top 5 failure modes

### 1. Run stuck / OOM

**Symptoms.** Run stays in `running` for > pipeline's expected duration. Backend RSS climbing. User reports "trigger returned run_id, nothing since." Frontend run detail polls forever.

**Diagnose.**

```bash
# Which runs are running right now?
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT id, pipeline_id, started_at, now() - started_at AS elapsed
     FROM runs WHERE status='running' ORDER BY started_at;"

# Tail backend logs for that run_id (structured JSON includes run_id tag)
docker compose logs --since=30m backend | grep '"run_id":"<RUN_ID>"'

# Memory pressure on the backend container
docker stats --no-stream dte-backend-1
```

**Mitigate.**

```bash
# Cancel via API. Default mode: reaches the in-process asyncio task.
# Distributed mode: queue-native abort via the run's job_id — works from any replica.
curl -X POST http://localhost:8001/api/runs/<RUN_ID>/cancel

# If cancel returns false (task already gone but row stuck), mark failed manually:
docker compose exec postgres psql -U dte -d dte -c \
  "UPDATE runs SET status='failed', error='manually cancelled — stuck task'
    WHERE id='<RUN_ID>' AND status='running';"

# Last resort. Default mode: recycle backend (kills ALL in-flight runs).
docker compose up -d --force-recreate backend
# Distributed mode: recycle only the workers — API stays up and serving.
docker compose up -d --force-recreate worker
```

**Distributed mode: prefer waiting to intervening.** Workers heartbeat every 30s and the reaper fails out any `running` run whose heartbeat is >60s stale. A run orphaned by a killed worker cleans itself up within ~a minute — check `last_heartbeat_at` before hand-editing rows:

```bash
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT id, status, now() - last_heartbeat_at AS heartbeat_age
     FROM runs WHERE status='running' ORDER BY started_at;"
```

A live `heartbeat_age` under 30s means the run is genuinely working, not stuck. Runs are **never** retried automatically — a partially-written destination is not safe to re-run unattended.

**Root-cause.** Check the `run_max_rows` guard (`dte/config.py`, enforced in the execution path — `dte/worker/tasks.py`). Pipelines that exceed the row ceiling raise `RunTimeout` / `RunCancelled` cleanly; if this isn't happening the guard is disabled or the step is DuckDB-native (raw SQL escape hatch) and bypasses row-count checks. Grep compiler for `con.sql(` to identify raw-SQL steps in the failing pipeline.

### 2. Postgres unreachable / connection pool exhausted

**Symptoms.** 500s on all API calls. `/readyz` returns `not_ready`. Backend logs full of `OperationalError` / `TimeoutError: QueuePool limit`. Frontend "Something went wrong" boundary firing everywhere.

**Diagnose.**

```bash
docker compose ps postgres                              # healthy?
docker compose logs --tail=200 postgres                 # OOM, disk full, WAL errors?
docker compose exec postgres pg_isready -U dte -d dte

# Active + idle connections
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT state, count(*) FROM pg_stat_activity WHERE datname='dte' GROUP BY state;"

# Long-running / blocking queries
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT pid, now()-query_start AS runtime, state, query
     FROM pg_stat_activity WHERE datname='dte' AND state<>'idle'
     ORDER BY runtime DESC NULLS LAST LIMIT 20;"
```

**Mitigate.**

```bash
# Kill a runaway query
docker compose exec postgres psql -U dte -d dte -c "SELECT pg_terminate_backend(<PID>);"

# Reset the backend pool (drops all connections; safe — no in-flight state is authoritative here)
docker compose up -d --force-recreate backend

# If Postgres itself is down
docker compose up -d postgres
```

**Root-cause.** Look for a route or background task holding a session across an `await` on external I/O. Every `Postgres*Store` should scope sessions per-call. Check for disk pressure (`docker compose exec postgres df -h`) and pg log rotation.

### 3. Source credential invalid / expired

**Symptoms.** Pipeline runs fail with HTTP 422, error text `SourceLoadError: ...`. Multiple pipelines sharing one connection all break at once.

**Diagnose.**

```bash
# Probe the connection directly
curl -s http://localhost:8001/api/connections/<CONN_ID>/test | jq
# → {"ok": false, "elapsed_ms": 812, "detail": "..."}

# Which sources reference it?
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT id, source_type FROM sources WHERE config->>'connection_id'='<CONN_ID>';"

# Recent failed runs and their errors
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT id, pipeline_id, error, finished_at FROM runs
     WHERE status='failed' AND finished_at > now() - interval '1 hour'
     ORDER BY finished_at DESC LIMIT 20;"
```

**Mitigate.** Rotate creds via the **Connections** page in the UI, or:

```bash
curl -X PUT http://localhost:8001/api/connections/<CONN_ID> \
  -H 'Content-Type: application/json' \
  -d '{"credentials": {"...new creds..."}}'
# Then re-probe
curl -s http://localhost:8001/api/connections/<CONN_ID>/test | jq
```

**Root-cause.** Cloud key rotation, expired IAM token, revoked HMAC pair, MongoDB user dropped. If the customer changed creds upstream without telling us, document in the incident and file a follow-up to add credential-expiry monitoring.

### 4. Backend container OOMKilled

**Symptoms.** Backend container restarting on a loop. `/healthz` intermittently 200 → connection refused. `docker inspect` shows `OOMKilled: true`. Container hits the 2G limit set in compose.

**Diagnose.**

```bash
docker inspect --format='{{json .State}}' dte-backend-1 | jq
# → look for "OOMKilled": true, "RestartCount"

# Confirm the ceiling
docker inspect dte-backend-1 | jq '.[0].HostConfig.Memory'   # 2147483648 = 2 GiB

# Which run was in flight when it died?
docker compose logs --since=15m backend | grep -E '"run_id"|OOM|Killed|MemoryError'

# History of failed runs — look for the pipeline that eats memory
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT pipeline_id, count(*) FROM runs
     WHERE status='failed' AND started_at > now() - interval '1 day'
     GROUP BY pipeline_id ORDER BY count DESC;"
```

**Mitigate.**

```bash
# Short term: bump the limit in docker-compose.yml (backend.deploy.resources.limits.memory) and
docker compose up -d backend

# Or block the offending pipeline until fixed
curl -X DELETE http://localhost:8001/api/pipelines/<PIPELINE_ID>
```

**Root-cause.** Streaming writers landed in P1 #16 — a pipeline still OOMing likely uses a raw-SQL step or a pivot (which materialises via `CREATE TEMP TABLE`). Reproduce with `GET /api/pipelines/<id>/preview?limit=1000` and watch `docker stats`. If innocent, revisit the container ceiling and the `run_max_rows` guard.

### 5b. Fresh operator locked out (no admin role)

**Symptoms.** Operator registers a user on a new deploy but `/api/pipelines` returns 403 `missing permission: pipeline:write`. First-user-becomes-admin failed because the users table was not empty (residual test users from an earlier attempt on the same `dte_pgdata` volume).

**Diagnose.**

```bash
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT u.email, array_agg(ur.role_id) FROM users u LEFT JOIN user_roles ur ON u.id = ur.user_id GROUP BY u.email;"
```

If the target email has no rows: it's locked out.

**Mitigate.**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://dte:dte@localhost:5432/dte \
  uv run python scripts/promote_admin.py --email <operator@example.com>
```

**Root cause.** `POST /api/auth/register` grants `admin` only when `users.count() == 0`. On a shared / reused DB this branch never fires. The register handler is intentionally single-shot; use `promote_admin.py` to recover.

---

### 5. Alembic migration failure at deploy

**Symptoms.** Backend container never reaches `uvicorn` line. Entrypoint logs show `alembic.util.exc.CommandError` / `sqlalchemy.exc.ProgrammingError`. `docker compose ps backend` shows `Exit N` on repeat.

**Diagnose.**

```bash
docker compose logs backend | head -100          # find the alembic traceback

# Which revision are we on?
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT version_num FROM alembic_version;"

# What revision does the image expect?
docker compose run --rm --entrypoint '' backend alembic heads
```

**Mitigate.**

```bash
# Roll back to previous image (assuming :prev tag exists)
docker compose pull backend
IMAGE=<previous-sha> docker compose up -d backend

# If we must un-apply the last migration on the running DB (only if reversible):
docker compose run --rm --entrypoint '' backend alembic downgrade -1
```

**Root-cause.** Dry-run the failing migration on a copy of prod:

```bash
# Snapshot prod
docker compose exec postgres pg_dump -U dte dte > /tmp/dte-prod.sql
# Restore into a scratch DB, then run the migration there. Do not retry on prod
# until the migration succeeds on the copy.
```

Big backfills must go through `dte.alembic_util.batched_update` (per CLAUDE.md) — a bare `UPDATE` on > 100k rows in a single migration is the usual culprit.

---

## Common commands (copy-paste)

```bash
# Tail backend logs filtered by request_id or run_id (structured JSON)
docker compose logs -f backend | grep '"request_id":"<RID>"'
docker compose logs -f backend | grep '"run_id":"<RUN_ID>"'

# Cancel a run
curl -X POST http://localhost:8001/api/runs/<RUN_ID>/cancel

# Recent failed runs from Postgres
docker compose exec postgres psql -U dte -d dte -c \
  "SELECT id, pipeline_id, error, started_at, finished_at
     FROM runs WHERE status IN ('failed','failed_quality')
     ORDER BY started_at DESC LIMIT 25;"

# Force-recycle a container (kills in-flight runs — see #1)
docker compose up -d --force-recreate backend

# External health probe
curl -m 5 -w 'code=%{http_code} time=%{time_total}s\n' https://<public-host>/healthz
curl -m 5 -w 'code=%{http_code} time=%{time_total}s\n' https://<public-host>/readyz

# Connection probe
curl -s http://localhost:8001/api/connections/<CONN_ID>/test | jq

# Docker resource pressure
docker stats --no-stream
docker inspect --format='{{json .State.Health}}' dte-backend-1 | jq
```

---

## Postgres backup and restore

### Current state (honest assessment)

As of 2026-07-27 there is **no automated backup**. The only durable copy of Postgres data is the Docker named volume `dte_pgdata` on the host running the compose stack. If that host's disk is lost — or the volume is accidentally deleted with `docker compose down -v` — all pipeline definitions, source configs, connection credentials, and run history are gone.

This is inadequate for real customer data. The immediate mitigation is to run the manual snapshot command below on a cron schedule (e.g. daily at 03:00 UTC) and copy the file to off-host storage (S3, GCS, or NAS) before any customer goes live.

---

### Manual snapshot (pg_dump)

```bash
# Run from the compose host. Produces a compressed SQL dump named by date.
docker compose exec postgres pg_dump -U dte dte \
  | gzip > backup-$(date +%F).sql.gz

# Verify the dump is non-empty (should be > a few KB for a live system)
ls -lh backup-$(date +%F).sql.gz

# Store off-host immediately — example: copy to S3
aws s3 cp backup-$(date +%F).sql.gz s3://<your-bucket>/dte-backups/
```

The `pg_dump` output is a plain SQL file. It is safe to run against a live database; it takes a consistent snapshot without locking writes.

---

### Restore from pg_dump backup

```bash
# 1. Stop the backend so no writes arrive during restore
docker compose stop backend

# 2. Drop and recreate the target database (Postgres must still be running)
docker compose exec postgres psql -U dte -c "DROP DATABASE IF EXISTS dte;"
docker compose exec postgres psql -U dte -c "CREATE DATABASE dte;"

# 3. Pipe the dump in (- flag reads from stdin; no shell variable expansion issues)
zcat backup-<DATE>.sql.gz \
  | docker compose exec -T postgres psql -U dte -d dte

# 4. Verify row counts look right
docker compose exec postgres psql -U dte -d dte \
  -c "SELECT 'pipelines' AS tbl, count(*) FROM pipelines
      UNION ALL SELECT 'runs', count(*) FROM runs
      UNION ALL SELECT 'sources', count(*) FROM sources;"

# 5. Restart backend (runs alembic upgrade head on entry, which is idempotent)
docker compose up -d backend
```

If the restore is going to a fresh host with a new compose stack, run `docker compose up -d postgres` first, wait for it to be healthy, then follow steps 2–5.

---

### Volume snapshot (faster for large databases)

A filesystem-level tarball of the `pgdata` volume is faster to create than pg_dump for large databases (no SQL serialisation) but is Postgres-version-sensitive — you must restore it on the same major version.

```bash
# Snapshot (postgres must be stopped cleanly first to avoid partial page writes)
docker compose stop postgres
docker run --rm \
  -v dte_pgdata:/data \
  -v $(pwd):/backup \
  alpine \
  tar czf /backup/pgdata-$(date +%F).tgz -C /data .
docker compose start postgres

# Restore (wipes the target volume entirely — destructive)
docker compose down
docker volume rm dte_pgdata
docker volume create dte_pgdata
docker run --rm \
  -v dte_pgdata:/data \
  -v $(pwd):/backup \
  alpine \
  tar xzf /backup/pgdata-<DATE>.tgz -C /data
docker compose up -d
```

Verify with `/api/readyz` after restart.

---

### Recovery time and point objectives

| Metric | Current state | Minimum acceptable for GA |
| --- | --- | --- |
| **RPO** (data loss window) | Unbounded — no automated backup | 24 hours (daily backup) |
| **RTO** (time to restore service) | 4–8 hours manual (operator available, backup on hand) | < 4 hours automated |

These figures are inadequate for real customer data. Recommended actions before scaled launch:

1. **Add daily cron backup to S3** — a `pg_dump | gzip | aws s3 cp` job scheduled at 03:00 UTC on the compose host reduces RPO to 24 hours. Cost: negligible (SQL dump of DTE metadata is typically < 500 MB even for thousands of pipelines).
2. **Retain 7 daily + 4 weekly snapshots** — use S3 lifecycle rules or a simple rotation script to avoid unbounded storage growth.
3. **Test the restore** — run through the restore steps above in a staging environment before relying on them in an incident.
4. **Enable Postgres WAL archiving** for RPO < 1 hour — requires `wal_level = replica` and an archiver like pgBackRest or Barman; deferred to a dedicated plan.
5. **Never run `docker compose down -v`** in production — the `-v` flag destroys named volumes including `dte_pgdata`. This is the most common accidental data-loss path. Treat it as a destructive operation equivalent to `DROP DATABASE`.

---

| Sev | Definition                                                                                                    | Response                                     |
| --- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| P0  | Full outage. All customers. Data loss suspected or confirmed. Credentials leaked.                              | Page primary + secondary + platform lead immediately. Status page within 15 min. |
| P1  | Partial outage: single tenant down, > 5% run failure rate for 15+ min, `/readyz` red > 3 min.                  | Page primary. Escalate to secondary at 15 min no-ack. |
| P2  | Degraded but functioning: single pipeline broken by user config, slow queries, non-blocking migration warnings. | Ticket; address next business day.           |

Contacts: on-call rotation in **PagerDuty schedule "DTE-primary"** (placeholder — replace with real link at deploy). Backup channel: `#dte-oncall` in Slack.
