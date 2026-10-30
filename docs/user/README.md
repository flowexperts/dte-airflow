# dte user guide

dte is a visual pipeline builder that runs inside Apache Airflow 3.3+. Pick a source, add steps, pick a destination. Every pipeline becomes an Airflow DAG, so it runs on demand or on a schedule, with Airflow's auth, connections and run history. No SQL required, though you can drop into it.

## Start here

1. [Install](self-hosting/install-plugin.md) into your Airflow, or [try it with Docker Compose](self-hosting/install.md)
2. [Find dte in Airflow](getting-started/01-sign-up.md)
3. [Build your first pipeline](getting-started/02-first-pipeline.md)
4. [Core ideas](getting-started/03-concepts.md): connection, source, destination, pipeline, run

## Reference

- [Connections](connections/index.md)
- [Sources](sources/index.md)
- [Destinations](destinations/index.md)
- [Steps](steps/index.md)
- [Pipelines](pipelines/building.md): [field names](pipelines/field-refs.md), [preview & run](pipelines/preview-and-run.md), [scheduling](pipelines/scheduling.md), [lookup tables](pipelines/lookup-tables.md)

## Running dte

- [Install into your own Airflow](self-hosting/install-plugin.md) · [Docker Compose](self-hosting/install.md)
- [Secrets & environment](self-hosting/secrets.md) · [Scaling](self-hosting/scaling.md) · [Upgrading](self-hosting/upgrading.md)
- [Architecture](architecture/overview.md) · [Data flow](architecture/data-flow.md)

## Help

- [Troubleshooting](troubleshooting.md)
- [FAQ](faq.md)
