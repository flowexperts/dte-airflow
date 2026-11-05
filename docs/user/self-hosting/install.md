# Try it with Docker Compose

Postgres plus the Airflow api-server, scheduler and dag-processor, with dte installed as a plugin. For your own Airflow, see [Install into your own Airflow](install-plugin.md).

## Prerequisites

- Docker Desktop (or Docker Engine + `docker compose` v2)
- Git, Python 3 (for `bootstrap.sh`)
- Free ports `8080`, `5432` and `5433` on localhost

## Bring the stack up

```bash
git clone https://github.com/flowexperts/dte-airflow.git
cd dte-airflow
scripts/bootstrap.sh       # writes .env: Fernet key, JWT secret, admin password
docker compose up -d --build
```

Compose won't start without `.env`. The first build takes a few minutes. Follow the api-server:

```bash
docker compose logs -f airflow-apiserver
```

## Open the app

<http://localhost:8080>. Log in as `admin` with the password `bootstrap.sh` printed (also in `.env`). dte is under **Plugins ▸ DTE Pipelines**.

## Ports

All bind to `127.0.0.1`. This is for local use, not a server deployment.

| Port | Service |
| ---- | ------- |
| 8080 | Airflow UI + REST API; DTE UI at `/plugin/dte`, API at `/dte/api` |
| 5432 | Postgres: Airflow metadata, with DTE's tables in the `dte` schema |
| 5433 | Demo warehouse |
| 9094 | Kafka broker (`kafka` profile only) |
| 8090 | Kafka UI (`kafka` profile only) |

## Kafka (optional)

`docker compose --profile kafka up -d` adds a Kafka broker and [Kafka UI](https://github.com/kafbat/kafka-ui), for trying the [Kafka source](../sources/kafka.md). Airflow reaches the broker as `kafka:9092`, your machine as `127.0.0.1:9094`. The broker keeps no volume: recreating it empties the topics.

## Where data lives

- `/tmp/dte-samples` is bind-mounted into the Airflow containers at the same path. It holds files read and written through the **Local files** connection. `/tmp` doesn't survive a reboot on most systems, so point production at a real path or object storage.
- Pipelines, sources, destinations and run results live in the `dte` schema of the Airflow metadata database, in the `airflow_pgdata` volume, next to Airflow's connections and run history.

Back up both.

## Next

[Secrets & environment](secrets.md) · [Scaling](scaling.md) · [Upgrading](upgrading.md) · [Architecture](../architecture/overview.md)
