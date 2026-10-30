# Core ideas

## Connection

Credentials for one system: a database, a bucket, an API. No table or folder. dte uses **Airflow connections**, so rotating a password in Airflow updates every pipeline on its next run. See [Connections](../connections/index.md).

## Source

Where inside a system your data lives. Picks a connection and adds details: folder and files, table or query, or API endpoint. Reusable across pipelines.

## Destination

Where a pipeline's result lands. A connection plus details (file path, table name).

## Pipeline

One or more sources, an ordered list of [steps](../steps/index.md), and a destination. Every pipeline is one Airflow DAG, `dte__<pipeline id>`. Every save is a new revision, listed on the **History** tab.

## Run

One execution of a pipeline, i.e. one Airflow dag run, with a status, row count, and start and end time. The pipeline's **Runs** tab keeps the history; Airflow shows the same runs with task logs.

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
