# Plan 022 — JWT authentication + user model

**Depends on plan 021.** Uses SQLModel for the `User` table.

## Problem

The API today is unauthenticated — anyone with network access to `:8001` can list/create/delete every pipeline, connection, and source. To ship this beyond a single-user local dev setup, and as the foundation for RBAC (plan 023) and FastAdmin (also 023), we need:

1. A `User` model persisted in Postgres.
2. Password hashing.
3. A `/auth/login` endpoint that issues a JWT.
4. A FastAPI dependency `current_user` that validates the bearer token on every protected route.

This plan is auth **only** — no permissions, no roles. Every authenticated user still gets access to every route. RBAC lands in plan 023 on top of this.

## Architecture

### User model (`backend/dte/models/user.py`, new file)

```python
class UserBase(SQLModel):
    email: EmailStr = SMField(sa_column=Column(Text, unique=True, nullable=False, index=True))
    is_active: bool = True

class User(UserBase, table=True):
    __tablename__ = "users"
    id: str = SMField(primary_key=True)   # uuid4
    password_hash: str
    created_at / updated_at   # mirror Pipeline

class UserCreate(UserBase):
    password: str   # plaintext at the edge; hashed before insert
```

Password hashing via `passlib[bcrypt]` — already a common dep; add to `pyproject.toml`.

### Store

`backend/dte/store/base.py` — add `UserStore` Protocol: `get_by_id`, `get_by_email`, `save`, `list`, `delete`.

`backend/dte/store/postgres.py` — `PostgresUserStore` in the ORM pattern.

`backend/tests/fakes.py` — `FakeUserStore`.

### Auth surface (`backend/dte/api/routes/auth.py`, new file)

```
POST   /api/auth/login       {email, password} → {access_token, token_type: "bearer"}
POST   /api/auth/register    {email, password} → {user_id, email}   # gated by DTE_ALLOW_REGISTRATION or admin token
GET    /api/auth/me          → current user (whoami)
```

Register is gated behind an env flag by default because RBAC (plan 023) will move user creation into the admin flow. During plan 022 rollout, `DTE_ALLOW_REGISTRATION=true` is set in `docker-compose.yml` so you can bootstrap the first user; production will flip it off.

### Token shape

`python-jose[cryptography]` for JWT. Payload:
```json
{ "sub": "<user_id>", "email": "...", "iat": ..., "exp": ... }
```

- Signing algorithm: **HS256** (symmetric secret from `DTE_JWT_SECRET`; hard-fail at startup if unset in production).
- TTL: 24h default, overridable via `DTE_JWT_TTL_SECONDS`.
- No refresh tokens in this plan — 24h suffices for internal use. Refresh flow can land later if needed.

### Dependency

`backend/dte/api/deps.py` — add `get_current_user`:

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    users: UserStore = Depends(get_user_store),
) -> User: ...
```

Uses `fastapi.security.OAuth2PasswordBearer(tokenUrl="/api/auth/login")` so Swagger UI gets a working "Authorize" button.

### Applying auth to existing routes

Add `dependencies=[Depends(get_current_user)]` at the **router level** in each of:
- `pipelines.py`, `runs.py`, `sources.py`, `destinations.py`, `connections.py`, `schema.py`

`auth.py` routes stay open (login / register).

Do **not** add per-route `Depends(get_current_user)` calls — router-level is uniform and avoids drift.

### Alembic migration

`010_users.py` — creates `users` table:
```sql
CREATE TABLE users (
  id           text PRIMARY KEY,
  email        text NOT NULL UNIQUE,
  password_hash text NOT NULL,
  is_active    boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX users_email_idx ON users(email);
```

Add the `updated_at` `BEFORE UPDATE` trigger from migration 003's pattern.

### Frontend impact

`frontend/src/lib/api.ts` — `apiFetch` reads token from `localStorage.getItem("dte_token")` and sets `Authorization: Bearer ...`. On 401, redirect to `/login`.

New pages:
- `src/app/(auth)/login/page.tsx` — form → `POST /api/auth/login` → store token → redirect to `/pipelines`.
- Sidebar footer shows current user's email + logout button (clears token, redirects to `/login`).

Middleware in `src/middleware.ts` — redirect unauthenticated requests to `/login` (except `/login` itself and static assets).

## Files changed / added

Added:
- `backend/dte/models/user.py`
- `backend/dte/api/routes/auth.py`
- `backend/dte/security/` — new package: `passwords.py` (bcrypt hash/verify), `jwt.py` (encode/decode)
- `backend/alembic/versions/010_users.py`
- `frontend/src/app/(auth)/login/page.tsx`
- `frontend/src/middleware.ts`

Changed:
- `backend/dte/store/base.py`, `postgres.py`, `memory.py`
- `backend/tests/fakes.py`, `conftest.py` — add `auth_headers` fixture that creates a user + returns `{"Authorization": "Bearer ..."}` for use in every existing route test
- `backend/dte/api/main.py` — mount `auth_router`, apply `dependencies=[Depends(get_current_user)]` to existing routers
- `backend/dte/api/deps.py` — add `get_user_store`, `get_current_user`
- `backend/pyproject.toml` — add `passlib[bcrypt]`, `python-jose[cryptography]`, `email-validator`
- `frontend/src/lib/api.ts` — token injection + 401 handling
- `frontend/src/components/app-sidebar.tsx` — user chip + logout

## Tasks

### Task 1 — user model + store  (branch `feature/auth-user-model`)

Model, migration, store, tests. No API routes yet.

### Task 2 — auth routes + JWT  (branch `feature/auth-jwt`)

`/auth/login`, `/auth/register`, `/auth/me`. `get_current_user` dependency. Router-level guards on existing routes. Update every existing route test with the `auth_headers` fixture.

### Task 3 — frontend auth  (branch `feature/auth-frontend`)

Login page, middleware, token in `apiFetch`, sidebar user chip.

## Verification

```bash
cd backend
uv run alembic upgrade head
uv run pytest -x

# manual
docker compose up -d --build
curl -X POST localhost:8001/api/auth/register -d '{"email":"me@x.com","password":"pw"}' -H 'content-type: application/json'
TOKEN=$(curl -s -X POST localhost:8001/api/auth/login -d '{"email":"me@x.com","password":"pw"}' -H 'content-type: application/json' | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" localhost:8001/api/pipelines
curl localhost:8001/api/pipelines   # expect 401
```

## Out of scope

- Password reset / email verification
- OAuth / SSO
- Refresh tokens
- Any per-user or per-role authorization — see plan 023
