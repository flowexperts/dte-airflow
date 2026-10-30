# Find dte in Airflow

dte has no login of its own. It's part of your Airflow, so open Airflow and sign in the way you always do. If you don't have dte installed yet, see [Install into your own Airflow](../self-hosting/install-plugin.md), or [try it with Docker Compose](../self-hosting/install.md).

## Where it lives

dte adds itself to Airflow's left rail:

- **Plugins ▸ DTE Pipelines ▸ Transform**: your pipelines. This is where you build, preview and run them.
- **Plugins ▸ DTE Pipelines ▸ Quality Check**: pipelines that only check data and don't write it anywhere.
- **Admin ▸ DTE Sources**: where data comes from.
- **Admin ▸ DTE Destinations**: where data lands.
- **Admin ▸ DTE Lookup tables**: small reference tables a pipeline can use.
- **Admin ▸ Connections**: Airflow's own connections. dte uses these for every database, bucket and API.

The first time you open **Transform**, the list is empty. That's expected, because you haven't built a pipeline yet.

## Who can do what

Airflow decides. dte follows Airflow's auth manager and DAG permissions: if you can see and trigger a `dte__…` DAG in Airflow, you can see and run that pipeline in dte.

## Next

- [Build your first pipeline →](02-first-pipeline.md)
