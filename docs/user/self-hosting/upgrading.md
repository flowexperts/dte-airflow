# Upgrading

dte is in beta, so read the release notes before every upgrade. Breaking changes and migration notes are called out per release.

## Before upgrading in production

1. **Back up dte's database**: the one `DTE_DATABASE_URL` points at (its `dte` schema). If that's Airflow's metadata database, back that up.
2. **Back up local files** used by any `fs` connection, if you rely on them.

## In your own Airflow

On every component (api-server, scheduler, dag-processor, workers), upgrade with the same Airflow constraints file you installed with:

```bash
pip install --upgrade dte-airflow --constraint constraints.txt
```

In a Docker image, bump the version in your Dockerfile and rebuild.

Then migrate once, with `DTE_DATABASE_URL` set, and restart Airflow:

```bash
dte db upgrade
```

The api-server serves the UI bundle from the installed package, so the new UI ships with the upgrade. Reload the page.

## Docker Compose stack

```bash
cd dte-airflow
git pull
docker compose up -d --build
```

The `airflow-init` service runs `airflow db migrate` and `dte db upgrade` before the other services start.

## Rolling back

If a migration goes wrong:

1. Stop Airflow.
2. Restore the database backup.
3. Install the previous version (`pip install dte-airflow==<previous> --constraint constraints.txt`), or for compose, `git checkout <previous-tag>` and `docker compose up -d --build`.
