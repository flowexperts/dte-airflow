# Core ideas

Five words. Learn them once and the rest of dte makes sense.

## Connection

A **connection** is the login to one system: a database, a cloud storage bucket, an API. It holds the credentials and nothing else. It doesn't know which table or which folder inside that system.

dte uses **Airflow connections**, the same ones your other DAGs use. You add a connection once, and every source or destination that talks to that system points at it. Rotate a password in Airflow, and every pipeline picks up the new value on its next run. See [Connections](../connections/index.md).

## Source

A **source** is *where inside a system your data lives*. It picks a connection and adds the details:

- For a file store: which folder, which files.
- For a database: which table (or a query).
- For an API: which endpoint.

Sources are reusable. Two pipelines can read the same source.

## Destination

A **destination** is *where the result of a pipeline lands*. It's the same idea as a source, in reverse: pick a connection, add the details (file path, table name), and you're done.

## Pipeline

A **pipeline** is a recipe: pick one or more sources, add an ordered list of steps, and pick a destination. Steps are the changes you make to the data, such as filter, rename and join. See [Steps](../steps/index.md) for the full list.

Every pipeline is one Airflow DAG, `dte__<pipeline id>`. Every save is a new revision, and the pipeline's **History** tab lists them.

## Run

A **run** is one execution of a pipeline, which means one Airflow dag run. It has a status, a row count, and a start and end time. The pipeline's **Runs** tab keeps the history, and Airflow shows the same runs with their task logs.

| Status | Meaning |
| --- | --- |
| `pending` | Queued in Airflow, not started yet |
| `running` | Reading, transforming, writing |
| `completed` | Done; the result is written |
| `completed_with_warnings` | Done, but a quality check with severity *warn* failed |
| `failed` | Something broke; the run shows the error |
| `failed_quality` | A quality check with severity *fail* failed. The run shows which check and why |

## The picture

```
Connection ─┐
            ├── Source ──┐
Connection ─┘            │
                         ├──►  Pipeline (= Airflow DAG)  ──►  Run (= dag run)
Connection ── Destination┘
```

One connection, many sources. One source, many pipelines. One pipeline, many runs.
