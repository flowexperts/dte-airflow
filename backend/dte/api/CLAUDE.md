## API surface

```
POST   /api/pipelines                     create pipeline (validates source/dest ids exist)
GET    /api/pipelines                     list pipelines
GET    /api/pipelines/{id}                get pipeline
PUT    /api/pipelines/{id}                update pipeline
DELETE /api/pipelines/{id}                delete pipeline
POST   /api/pipelines/{id}/trigger        start async run → {run_id}
GET    /api/pipelines/{id}/preview?limit  compile + execute on sample rows
GET    /api/pipelines/{id}/runs?limit     run history per pipeline
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
POST   /api/connections                   create connection (409 on id collision; creds encrypted at rest)
GET    /api/connections                   list connections (credentials masked)
GET    /api/connections/{id}              read (?reveal=true for plaintext creds)
PUT    /api/connections/{id}              update (empty credentials keeps existing)
DELETE /api/connections/{id}              409 with {referenced_by: {sources, destinations}} if in use
POST   /api/connections/{id}/test         connectivity probe → {ok, elapsed_ms, detail}
GET    /api/connections/{id}/schemas      schemas/databases visible to a DB connection (422 if no native backend)

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

`Run` responses include `id`, `pipeline_id`, `status` (`pending`/`running`/`completed`/`failed`), `error`, `rows_written`, `started_at`, `finished_at`. Per-step run events are **not** recorded yet — the frontend `Timeline` renders an empty state placeholder.

`finished_at` is written by the Postgres store, not the API code. Migration `003` installs a `BEFORE UPDATE` trigger on `runs` that stamps `finished_at = NOW()` when `status` becomes `completed` or `failed`. `MemoryRunStore.update` mirrors the rule. If you introduce a new terminal status, extend both.

