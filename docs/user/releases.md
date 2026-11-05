# Release notes

Newest first. dte is in beta: read the notes for every version between yours
and the target before [upgrading](./self-hosting/upgrading.md). Docs for a
specific release live at `/docs/<version>/`, e.g. [/docs/v0.1.0/](https://dte.flowexperts.ai/docs/v0.1.0/).

## Unreleased

- **Kafka source** ([guide](./sources/kafka.md)): each run reads the messages
  since the last successful run and moves the position only after the write
  succeeds. Runs with nothing new are skipped, not failed. Install
  `dte-airflow[kafka]`.
- **PostgreSQL Merge takes a key**: `primary_key` on a PostgreSQL destination.
  Merge used to behave like Append, since there was no way to name the key.

## v0.1.0 — 2026-11-03

First public beta, published to PyPI as `dte-airflow`.

- Runs as an Airflow 3.3 plugin: install with Airflow's constraints file, UI
  under **Plugins ▸ DTE Pipelines**, API at `/dte/api`.
- Visual pipeline builder for Transform and Quality Check pipelines; every
  pipeline is a `dte__<id>` DAG.
- Sources and destinations over Airflow connections; DTE tables in the `dte`
  Postgres schema, migrated with `dte db upgrade`.
- `dte validate` / `dte run` / `dte export` for pipelines kept in git.
