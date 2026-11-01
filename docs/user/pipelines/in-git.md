# Pipelines in git

A pipeline can live as a YAML file instead of only as a database row. Then you can review a change in a pull request, check it in CI, and promote it from dev to prod by copying a file.

This is opt-in. Set `DTE_PIPELINE_STORE=file` on every Airflow component (api-server, scheduler, dag-processor). The default, `postgres`, keeps pipelines in the database as before.

## Layout

```
$DTE_PIPELINES_DIR/
  orders_daily.yaml        one file per pipeline, named <pipeline id>.yaml
  big_orders.yaml
  sources/                 written by `dte export`; read only by `dte run`
    orders.yaml
  destinations/
    out.yaml
```

- `DTE_PIPELINES_DIR` must be a directory shared by the api-server (which writes it when you save in the UI) and the dag-processor (which reads it). Docker Compose mounts a `pipelines` volume at `/var/lib/dte/pipelines`.
- A file holds exactly what the pipeline editor saves: name, sources, steps, output, schedule, notifications. The `id` inside must match the file name.
- Sources and destinations are referenced by id. Credentials are never in the file. They stay in Airflow Connections.
- Each file becomes the DAG `dte__<id>`. A file that doesn't parse or validate loses only its own DAG, and the dag-processor log names the file. The rest keep running.
- File mode doesn't declare Airflow Assets yet, so it can't be combined with [After upstream](scheduling.md#chaining) schedules: those DAGs never run. Use cron schedules.
- A run records the revision it ran. In file mode that is a hash of the file's contents, so editing the file makes a new Airflow DAG version.

### Committing on save

If `DTE_PIPELINES_DIR` is a git checkout and `DTE_PIPELINES_GIT_COMMIT=true`, every save or delete in the UI makes a commit of that one file. dte never pushes. Push from a cron job or CI, or by hand.

## Moving existing pipelines to files

Run this once, with `DTE_DATABASE_URL` set, before you switch the setting:

```bash
dte export --out "$DTE_PIPELINES_DIR"
```

It writes the latest revision of every pipeline, plus `sources/` and `destinations/`. If a pipeline no longer passes validation in this version, it is still written as it was and reported with a `WARN` line, so nothing is lost. Fix it, then run `dte validate` on it.

## Checking files in CI

```bash
dte validate pipelines/*.yaml
```

This loads each file with the same model the API and the DAG factory use. It prints `ok` or `FAIL <file>: <reason>` per file and exits non-zero if any file fails. Run it on every pull request.

## Running a file locally

```bash
export AIRFLOW_CONN_LOCAL_FS='fs://'
dte run pipelines/big_orders.yaml --sample 100
```

`dte run` needs no database and no Airflow services. Sources and destinations come from `sources/<id>.yaml` and `destinations/<id>.yaml` next to the file (`--refs DIR` to look elsewhere). Their connections come from Airflow's `AIRFLOW_CONN_*` environment variables. `--sample N` caps the rows written. It writes to the real destination and prints a JSON summary.

## Promoting between environments

Environments differ only in their Airflow Connections. The pipeline file doesn't change. To promote, copy the file into the other environment's `DTE_PIPELINES_DIR`, by merging a branch or copying it in a deploy step. The dag-processor picks it up on its next parse.

Make sure the sources and destinations the file names exist in the target environment with the same ids.
