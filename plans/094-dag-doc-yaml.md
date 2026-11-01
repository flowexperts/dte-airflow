# 094 — The DAG page shows the pipeline YAML

## Problem

From Airflow's DAG page there is no way to see what the pipeline does, or to
get back to it in DTE, short of the Code tab (the shared factory file).

## Decision

Airflow's native DAG docs: `_dag_for` sets `doc_md` to an "Open in DTE" link
plus the pipeline as a fenced YAML block, from `store/files.dump_yaml` — the
same YAML the revision page and `dte export` show. No UI code. The link is
relative so Airflow's `<base href>` resolves it under any subpath.

Not doing: a DTE tab on the DAG page (`react_apps` `destination: "dag"`);
revisit if the docs dialog is too small for long pipelines.

## Tasks

### 1. `feature/094-dag-doc-yaml`
- Test: `doc_md` holds the link and YAML that loads back to the config.

## Files

Changed: `backend/dte/airflow/dag_factory.py`,
`backend/tests/airflow/test_dag_factory.py`.
