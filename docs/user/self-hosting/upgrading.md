# Upgrading

dte follows normal Docker Compose upgrade flow.

## Steps

```bash
cd dte
git pull
docker compose pull      # optional if you build locally
docker compose up -d --build
```

The backend container runs `alembic upgrade head` on start, so database schema migrations apply automatically. Check the logs:

```bash
docker compose logs -f backend
```

Wait for `Application startup complete`.

## Before upgrading in production

1. **Back up Postgres.** `pgdata` volume — snapshot, or `pg_dump` from inside the container.
2. **Back up `./data`.** Any files served by the **Local files** connection.
3. **Read the release notes.** Breaking changes and migration notes are called out per release.

## Rolling back

If a migration goes wrong:

1. Stop the backend: `docker compose stop backend`.
2. Restore the Postgres snapshot.
3. Check out the previous git tag: `git checkout <previous-tag>`.
4. `docker compose up -d --build backend`.

## Zero-downtime

Not supported by the default Compose deployment — the frontend and backend restart during `up -d --build`. If you need it, put the backend behind a load balancer and roll instances.

## Frontend rebuild after env changes

`NEXT_PUBLIC_*` variables are baked into the frontend at build time. Change one → rebuild:

```bash
docker compose build frontend && docker compose up -d frontend
```
