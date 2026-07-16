# Plan 017 — FastAdmin admin panel

**Depends on plan 018 (SQLAlchemy ORM migration).** Land 018 first — this plan assumes `dte/store/models.py` exists and every table has a mapped class.

## Problem

Ops / support work today requires either psql, hand-rolled scripts, or the app UI (which only exposes pipeline-shaped concerns). We need a low-friction admin surface to:

- inspect and edit rows in `pipelines`, `sources`, `destinations`, `connections`, `runs`
- recover from bad state (mark a stuck run as `failed`, delete an orphaned source, rotate a broken connection blob)
- give non-engineers a read-only browse over prod data behind auth

Building a bespoke admin is not worth it. [FastAdmin](https://github.com/vsdudakov/fastadmin) is a Django-admin-style panel that plugs into FastAPI and supports SQLAlchemy models.

## Architecture change

### Mount

FastAdmin runs as a separate ASGI app mounted at `/admin` on the existing FastAPI instance in `dte/api/main.py`. It binds to the ORM models from plan 018 (`dte/store/models.py`). Uses the same `DATABASE_URL` — async if FastAdmin's SQLAlchemy provider supports it now, sync engine (strip `+asyncpg`) otherwise. Confirm in task 1.

### Auth

FastAdmin's login expects a user model with `username` / `password_hash` and `is_superuser`. Add one:

- Alembic migration 006 → `admin_users` table
- mapped class `AdminUser` in `dte/store/models.py`
- seed one user from `DTE_ADMIN_USERNAME` / `DTE_ADMIN_PASSWORD` at container boot (idempotent upsert in `dte/admin/bootstrap.py`, called from FastAPI `lifespan`)
- session secret from `DTE_ADMIN_SECRET_KEY`; hard-fail on startup if `DTE_ADMIN_ENABLED=true` and it's unset

`/admin` is opt-in via `DTE_ADMIN_ENABLED` (off by default; on in compose).

### Credentials safety

`Connection.credentials_encrypted` is an opaque `BYTEA` blob (Fernet or plain JSON depending on `DTE_SECRETS_BACKEND`). Register the field **read-only and masked** ("••• hidden — edit via app UI"). Editing credentials stays in the app so it routes through the injected `SecretResolver`. Do not expose a "decrypt in admin" affordance — that would bypass the resolver seam.

### Read-only vs editable per model

- `Pipeline`, `Source`, `Destination` — full CRUD
- `Connection` — CRUD, but `credentials_encrypted` field is read-only
- `Run` — read + delete only (no create, no edit; runs are produced by the executor)
- `AdminUser` — CRUD, superuser-only

## Tasks

Each task on its own worktree.

### Task 1 — dependency + skeleton mount

Branch: `feature/fastadmin-skeleton`

- add `fastadmin` to `backend/pyproject.toml`; `uv lock`
- confirm FastAdmin's async SQLAlchemy provider status; pick sync or async engine accordingly
- `backend/dte/admin/__init__.py`, `backend/dte/admin/app.py` — FastAdmin instance bound to `Base` from `dte/store/models.py`
- mount at `/admin` in `dte/api/main.py` behind `DTE_ADMIN_ENABLED`
- smoke test: `GET /admin` → 200 (login page) when enabled, 404 when not
- `docker-compose.yml` — pass `DTE_ADMIN_ENABLED`, `DTE_ADMIN_SECRET_KEY`, `DTE_ADMIN_USERNAME`, `DTE_ADMIN_PASSWORD` to backend

### Task 2 — admin registrations

Branch: `feature/fastadmin-registrations`

- `backend/dte/admin/registrations.py` — one `ModelAdmin` per model per the read/write matrix above
- `Pipeline.definition`, `Source.config`, `Destination.config` (jsonb) → JSON widget
- `Connection.credentials_encrypted` → read-only + masked
- `Run` → list + detail + delete, no create/edit
- imported side-effect from `dte/admin/app.py`

### Task 3 — auth + user seeding

Branch: `feature/fastadmin-auth`

- Alembic migration `006_admin_users.py`
- `AdminUser` mapped class in `dte/store/models.py` + `ModelAdmin` registration
- `backend/dte/admin/bootstrap.py::ensure_seed_user()` invoked from a FastAPI `lifespan` handler when `DTE_ADMIN_ENABLED`
- integration test: seed a user, POST login, hit an admin list endpoint, assert 200

### Task 4 — docs

Branch: `feature/fastadmin-docs`

- add an **Admin** section to `CLAUDE.md`: how to enable, env vars, seed-user behavior, the "don't edit credentials here" rule, link to plan 018 for the underlying ORM
- do not link `/admin` from the frontend sidebar (out of v1)

## Files changed / added

Added:
- `backend/dte/admin/__init__.py`
- `backend/dte/admin/app.py`
- `backend/dte/admin/registrations.py`
- `backend/dte/admin/bootstrap.py`
- `backend/alembic/versions/006_admin_users.py`
- `backend/tests/integration/test_admin_auth.py`

Changed:
- `backend/pyproject.toml` (+ `fastadmin`, sync driver if needed)
- `backend/dte/api/main.py` (conditional mount + lifespan hook)
- `backend/dte/store/models.py` (+ `AdminUser`)
- `docker-compose.yml` (admin env vars)
- `CLAUDE.md` (Admin section)

Deleted: none.

## Out of scope

- Row-level per-user permissions beyond `is_superuser`
- Custom admin actions (bulk retry runs, rotate connection creds) — file follow-ups
- Linking `/admin` from the frontend sidebar
