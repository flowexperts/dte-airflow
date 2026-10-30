# dte user guide

Map it once. Run it forever.

dte is a visual pipeline builder that runs inside Apache Airflow 3.3+. Pick where your data is, draw the changes you want, and pick where the result should go. Every pipeline becomes an Airflow DAG, so it runs on demand or on a schedule, with Airflow's logins, connections and run history.

No code, and no SQL required (though you can drop into SQL when you need to).

## Start here

1. [Install](self-hosting/install-plugin.md) into your Airflow, or [try it with Docker Compose](self-hosting/install.md)
2. [Find dte in Airflow](getting-started/01-sign-up.md)
3. [Build your first pipeline in 10 minutes](getting-started/02-first-pipeline.md)
4. [Core ideas](getting-started/03-concepts.md): connection · source · destination · pipeline · run

## Reference

- **[Connections](connections/index.md)**: Airflow connections, and which ones dte can use
- **[Sources](sources/index.md)**: where your data comes from
- **[Destinations](destinations/index.md)**: where the result lands
- **[Steps](steps/index.md)**: everything you can do to your data
- **[Pipelines](pipelines/building.md)**: putting it all together
  - [Field names](pipelines/field-refs.md) · [Preview & run](pipelines/preview-and-run.md) · [Scheduling](pipelines/scheduling.md) · [Lookup tables](pipelines/lookup-tables.md)

## Running dte

- [Install into your own Airflow](self-hosting/install-plugin.md) · [Docker Compose](self-hosting/install.md)
- [Secrets & environment](self-hosting/secrets.md) · [Scaling](self-hosting/scaling.md) · [Upgrading](self-hosting/upgrading.md)
- [Architecture](architecture/overview.md) · [Data flow](architecture/data-flow.md)

## Help

- [Troubleshooting](troubleshooting.md)
- [FAQ](faq.md)
