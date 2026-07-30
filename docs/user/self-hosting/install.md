# Install

dte ships as a Docker Compose stack: Postgres + a FastAPI backend + a Next.js frontend.

## Prerequisites

- Docker Desktop (or Docker Engine + `docker compose` v2)
- Git
- Free ports on `3000`, `8001`, and `5432`

## Bring the stack up

```bash
git clone https://github.com/bhavaniravi/dte.git
cd dte
./scripts/bootstrap.sh     # writes .env with fresh secrets
docker compose up -d --build
```

First build takes a few minutes. Follow the backend:

```bash
docker compose logs -f backend
```

Wait for `Application startup complete`.

## Open the app

<http://localhost:3000>

The first account to sign up becomes admin.

## Ports

| Port | Service |
| ---- | ------- |
| 3000 | Frontend (Next.js) |
| 8001 | Backend API + OpenAPI docs at `/docs` |
| 5432 | Postgres |

## Where data lives

Docker Compose mounts `./data` at the repo root into the backend container as `/data`. Files that users read/write through the **Local files** connection live here. Include this directory in backups.

Pipeline metadata — pipelines, sources, destinations, connections, run history — lives in the Postgres volume `pgdata`. Include this in backups too.

## Next

- [Secrets & environment](secrets.md)
- [Upgrading](upgrading.md)
- [Architecture overview](../architecture/overview.md)
