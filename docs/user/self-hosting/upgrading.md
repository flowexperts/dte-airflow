# Upgrading

dte is in beta. Read the release notes before every upgrade.

## Before upgrading in production

1. Back up the database `DTE_DATABASE_URL` points at (its `dte` schema). If that's Airflow's metadata database, back that up.
2. Back up local files used by any `fs` connection.

## In your own Airflow

On every component, with the same constraints file you installed with:

```bash
pip install --upgrade dte-airflow --constraint constraints.txt
```

In a Docker image, bump the version and rebuild. Then migrate once, with `DTE_DATABASE_URL` set, and restart Airflow:

```bash
dte db upgrade
```

The api-server serves the UI bundle from the installed package, so reload the page.

## Docker Compose stack

```bash
cd dte-airflow
git pull
docker compose up -d --build
```

The `airflow-init` service runs `airflow db migrate` and `dte db upgrade` before the others start.

## Rolling back

1. Stop Airflow.
2. Restore the database backup.
3. Install the previous version (`pip install dte-airflow==<previous> --constraint constraints.txt`), or for compose, `git checkout <previous-tag>` and `docker compose up -d --build`.
