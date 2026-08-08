# Scaling and execution

By default dte runs every pipeline **inside the API process**, as a background task. That is
the right shape for a single-team install and it is what `docker compose up` gives you.

It has one consequence worth understanding before you hit it: a pipeline's memory is the API
process's memory. A large join or pivot competes with the HTTP requests serving the UI.

This page covers the knobs for that, and how to move execution onto separate workers when the
single-process model stops fitting.

## Two modes

| | Default | Distributed |
| --- | --- | --- |
| Where runs execute | Inside the API process | Separate `dte-worker` processes |
| Set by | nothing — this is the default | `DTE_JOB_QUEUE_ENABLED=true` |
| Queue | none | Postgres (no new datastore) |
| Scale execution independently | no | yes |
| Cancel works across replicas | no | yes |

Distributed mode is off unless you turn it on. Upgrading dte will not change how your install
behaves.

## Staying single-process

Most installs should. Before adding workers, check whether a limit is enough:

| Setting | Default | What it does |
| --- | --- | --- |
| `DTE_RUN_TIMEOUT_SECONDS` | `1800` (30 min) | Fails a run that exceeds it |
| `DTE_RUN_MAX_ROWS` | `10000000` | Ceiling on rows a run may process |

If a single pipeline is the problem, raising the backend container's memory is the simpler
fix — in `docker-compose.yml` under `services.backend.deploy.resources.limits.memory`. Note
this raises the ceiling for *everything*, not just the offending pipeline. That trade-off is
the reason distributed mode exists.

## Turning on distributed execution

Set on **both** the API and the worker:

```yaml
DTE_JOB_QUEUE_ENABLED: "true"
```

And run at least one worker process:

```bash
python -m dte.worker
```

The bundled `docker-compose.yml` already defines a `worker` service that does this. Bring it
up the usual way:

```bash
docker compose up -d --build
docker compose logs -f worker
```

What changes: `POST /api/pipelines/{id}/trigger` inserts the run row and enqueues a job in the
same transaction, then returns `{"run_id": ...}` exactly as before. A worker picks the job up
and executes it. **The API contract does not change** — nothing in the UI or any script you
have written needs updating.

The queue lives in Postgres. There is no Redis or RabbitMQ to run, back up, or monitor.

### Shared filesystem — read this before splitting pods

Pipelines using the **Local files** connection read and write the container's own filesystem.
If the API and workers do not share that filesystem, a worker writes an output the API cannot
read back, and `GET /api/runs/{id}/output` fails.

dte will not let you find this out at 2am. When `DTE_JOB_QUEUE_ENABLED` is on and
`DTE_SHARED_OUTPUT_FS` is off, triggering a pipeline that touches a `local_fs` source or
destination is rejected immediately:

```
422  {"code": "local_fs_not_shared", "offending_ids": [...]}
```

Two ways forward:

- **Use object storage** (`s3`, `gcs`, `azure`) for sources and destinations. These are
  pod-agnostic and are the supported path for a multi-node deployment.
- **Mount a shared volume** across the API and workers (NFS, EFS, or any RWX volume), then set
  `DTE_SHARED_OUTPUT_FS=true`.

Docker Compose on one host satisfies this already — the bundled `worker` service shares the
same bind mount as `backend`, so both flags ship as `"true"` there.

## Kubernetes

Three Deployments from two images:

| Deployment | Command | Notes |
| --- | --- | --- |
| `dte-api` | `uvicorn dte.api.main:app` | Stateless once execution moves off it. Scale on request rate. |
| `dte-worker` | `python -m dte.worker` | Memory-heavy. This is where run memory limits belong. |
| `dte-frontend` | `next start` | Unchanged. |

Two things the Compose setup does that do **not** carry over:

1. **Run migrations as a separate Job**, not in the container entrypoint. The Compose backend
   runs `alembic upgrade head` before starting uvicorn; with more than one API replica that
   races. Use a pre-upgrade hook or an init Job.
2. **Set a real memory limit on `dte-worker`.** At one run per worker, the limit is the ceiling
   for a single pipeline — a much more useful knob than a shared API limit.

dte does not ship a Helm chart. The images and env vars above are the whole contract.

## Recovering from a killed worker

A worker that dies mid-run — an evicted pod, an OOM kill — would otherwise leave its run
`running` forever. Each worker heartbeats every 30s while executing, and a reaper fails out
any run whose heartbeat is more than 60s stale, with an error explaining what happened.

Runs are **not** retried automatically. A pipeline that partially wrote to its destination is
not safe to re-run unattended, so dte fails it and leaves the decision to you. Re-trigger when
you have checked the destination.

## Next

- [Install](install.md)
- [Secrets & environment](secrets.md)
- [Upgrading](upgrading.md)
