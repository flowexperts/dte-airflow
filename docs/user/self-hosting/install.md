# Install

dte ships as an Airflow 3.3 app. The Docker Compose stack runs Postgres plus
the Airflow api-server, scheduler and dag-processor, with DTE installed as a
plugin.

## Prerequisites

- Docker Desktop (or Docker Engine + `docker compose` v2)
- Git, Python 3 (for `bootstrap.sh`)
- Free ports `8080`, `5432` and `5433` on localhost

## Bring the stack up

```bash
git clone https://github.com/flowexperts/dte-airflow.git
cd dte-airflow
scripts/bootstrap.sh       # writes .env: Fernet key, JWT secret, admin password
docker compose up -d --build
```

Compose won't start without `.env`. The first build takes a few minutes.
Follow the api-server:

```bash
docker compose logs -f airflow-apiserver
```

## Open the app

<http://localhost:8080>. Log in as `admin` with the password `bootstrap.sh`
printed (it's also in `.env`). DTE is under **Plugins ▸ DTE Pipelines**.

## Ports

All ports bind to `127.0.0.1`. This stack is for local use; it isn't a server
deployment.

| Port | Service |
| ---- | ------- |
| 8080 | Airflow UI + REST API; DTE UI at `/plugin/dte`, API at `/dte/api` |
| 5432 | Postgres: Airflow metadata, with DTE's tables in the `dte` schema |
| 5433 | Demo warehouse |

## Where data lives

Docker Compose bind-mounts `/tmp/dte-samples` into the Airflow containers at the same path. Files that users read/write through the **Local files** connection live here. Include this directory in backups. `/tmp` doesn't survive a reboot on most systems, so point production installs at a real path or use object storage.

Pipeline metadata (pipelines, sources, destinations, run results) lives in the `dte` schema of the Airflow metadata database, in the `airflow_pgdata` volume. Connections and run history are Airflow's own tables in the same database. Include it in backups too.

## Next

- [Secrets & environment](secrets.md)
- [Scaling and execution](scaling.md)
- [Upgrading](upgrading.md)
- [Architecture overview](../architecture/overview.md)
