# Core ideas

Five words. Learn them once, the rest of the app makes sense.

## Connection

A **connection** is dte's login to one system — a database, a cloud storage bucket, an API. It holds the credentials and nothing else. It doesn't know which table or which folder inside that system.

You add a connection once. Every source or destination that talks to that system points at it.

Rotate a password? Update the connection. Every pipeline that uses it picks up the new value on the next run.

## Source

A **source** is *where inside a system your data lives*. It picks a connection and adds the details:

- For a file store — which folder, which files.
- For a database — which table (or a query).
- For an API — which endpoint.

Sources are reusable. Two pipelines can read the same source.

## Destination

A **destination** is *where the result of a pipeline lands*. Same idea as a source, in reverse. Pick a connection, add the details (file path, table name), done.

## Pipeline

A **pipeline** is a recipe: pick one or more sources, add an ordered list of steps, pick a destination. Save. Run.

Steps are the changes you make to the data — filter, rename, join, and so on. See [Steps](../steps/index.md) for the full list.

## Run

A **run** is one execution of a pipeline. It has a status (`pending`, `running`, `completed`, `failed`), a row count, a start and end time. The **Runs** page keeps the history.

If a run fails, the page shows why.

## The picture

```
Connection ─┐
            ├── Source ──┐
Connection ─┘            │
                         ├──►  Pipeline  ──►  Run
Connection ── Destination┘
```

One connection, many sources. One source, many pipelines. One pipeline, many runs.
