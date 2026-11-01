## API surface

Mounted by the Airflow plugin at `/dte`, so every path below is served as `/dte/api/...`. Auth is Airflow's (`dte/airflow/auth.py`).

```
POST   /api/pipelines                     create pipeline (validates source/dest ids exist)
GET    /api/pipelines                     list pipelines
GET    /api/pipelines/{id}                get pipeline
PUT    /api/pipelines/{id}                update pipeline
DELETE /api/pipelines/{id}                delete pipeline
POST   /api/pipelines/{id}/trigger        validate, then start an Airflow dag run of the latest revision → {run_id}
GET/PUT/DELETE /api/pipelines/{id}/schedule  the pipeline's one schedule; each change is a revision
GET/PUT /api/pipelines/{id}/notifications    Airflow provider notifiers on run events (manual + scheduled); each change is a revision
GET    /api/notifiers                     installed provider notifiers + their constructor params
POST   /api/runs/{run_id}/cancel           mark the dag run failed
GET    /api/me                            Airflow user + derived DTE permissions
GET    /api/pipelines/{id}/preview?limit  compile + execute on sample rows
GET    /api/pipelines/{id}/runs?limit     latest runs per pipeline (no offset; full history is Airflow's grid)
GET    /api/allowed-ops                   ALLOWED_OPS: step ops each pipeline type may hold
GET    /api/assets                        each transform pipeline's output Asset URI, for "after upstream" schedules
GET    /api/runs/{run_id}                 poll run status
GET    /api/runs/{run_id}/output?limit    peek at the run's output file
POST   /api/schema/infer?table=           field tree from an in-flight Source body (table required for sql_database)
POST   /api/sources                       create source (409 on id collision)
GET    /api/sources                       list sources
GET    /api/sources/{id}                  get source
PUT    /api/sources/{id}                  update source
DELETE /api/sources/{id}                  409 with {referenced_by: [...]} if any pipeline uses it
GET    /api/sources/{id}/schema?table=    field tree for a saved source (table required for sql_database)
GET    /api/sources/{id}/tables           tables in a sql_database source's schema (422 for other kinds)
POST   /api/destinations                  create destination
GET    /api/destinations                  list destinations
GET    /api/destinations/{id}             get destination
PUT    /api/destinations/{id}             update destination
DELETE /api/destinations/{id}             409 with {referenced_by: [...]} if any pipeline uses it
GET    /api/connections                   Airflow Connections DTE can map (read-only; manage them in Airflow)
GET    /api/connections/{id}              read (credentials masked)
POST   /api/connections/{id}/test         connectivity probe → {ok, elapsed_ms, detail}
GET    /api/connections/{id}/schemas      schemas/databases visible to a DB connection (422 if no native backend)
GET    /api/destinations/{id}/schema      columns of a DB destination's target table (422 for file targets)
POST   /api/schema/automap                propose a source→destination column mapping

POST   /api/eval-sets                     create eval set
GET    /api/eval-sets                     list (+ best_macro_f1, last_run_at)
GET/PUT/DELETE /api/eval-sets/{id}        read / update / delete (409 if scheduled)
POST   /api/eval-sets/{id}/examples       upsert one label on (eval_set_id, doc_key)
GET    /api/eval-sets/{id}/examples       list labels
DELETE /api/eval-sets/{id}/examples/{eid} remove a label
POST   /api/eval-sets/{id}/examples:import CSV/JSONL bulk import
POST   /api/eval-sets/{id}/bootstrap      consensus over N variants (confirm to write)
POST   /api/eval-sets/{id}/propose        LLM-judge labels (confirm to write)
POST   /api/eval-sets/{id}/sweep          estimate, then confirm to enqueue one run/cell
POST   /api/eval-sets/{id}/promote        copy a winning config into a transform pipeline
GET    /api/eval-sets/{id}/leaderboard    ranked runs; ties within the Wilson interval
GET    /api/eval-sets/{id}/fields/{f}/failures  expected-vs-got for one field

POST   /api/pipelines/{id}/as-eval        eval twin of a pipeline (idempotent)
POST   /api/eval-sets:for-pipeline        eval set derived from a pipeline (idempotent)
GET    /api/sweeps/{sweep_id}/comparison  configs side by side; works with no labels
```

A **run** is an Airflow dag run of a `dte__*` DAG merged with its `dte.run_results` row (`PostgresRunStore`, `_merge`; dag runs come through Airflow's session, plan 075). Status and timing come from `dag_run`; rows, quality, SQL, scores and per-step events come from the operator's `run_results` row. `status` is `pending`/`running`/`completed`/`completed_with_warnings`/`failed_quality`/`failed`.

