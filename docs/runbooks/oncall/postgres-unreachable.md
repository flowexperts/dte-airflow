# Runbook: Postgres unreachable

**Symptom**: `/readyz` returns 503 with `postgres: unreachable`. API requests that touch the DB return 500. `dte.access` logs show sqlalchemy `OperationalError`.

## First checks

1. Confirm the container is alive:
   ```
   docker compose ps postgres
   ```
2. Tail Postgres logs:
   ```
   docker compose logs postgres --tail=50
   ```
3. Check connection saturation from inside the DB:
   ```
   docker compose exec postgres psql -U dte -c "SELECT count(*) FROM pg_stat_activity;"
   ```
   If close to `max_connections` (default 100), the pool is exhausted — see mitigation.

## Mitigation

- **Container crashed** — `docker compose restart postgres`. Backend reconnects automatically. Runs in flight fail with `cancelled`.
- **Connection storm** — kill idle backends:
  ```
  docker compose exec postgres psql -U dte -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state='idle' AND state_change < now() - interval '10 minutes';"
  ```
- **Disk full** — verify with `df -h` inside the container. Truncate WAL or extend the `pgdata` volume.

## Root-cause hunts

- If restarts are recurring: check `postgres.log` for OOM (increase memory limit) or WAL fill (increase `pgdata` volume, tune checkpoint intervals).
- If the pool is filling on a stable schedule: look for a runaway background task holding a session.

## Escalation

Any Postgres outage > 5 min triggers automatic downtime attribution against SLO 3. Post in `#dte-incident` immediately.
