# Plan 023 — Per-resource RBAC + FastAdmin mount

**Depends on plan 021 (SQLModel entities) and plan 022 (JWT auth + User).** This plan adds authorization on top of authentication, and mounts FastAdmin sharing the same user table.

## Problem

Plan 022 gets us "authenticated or not". We need finer control: some teammates should be able to trigger pipelines but not delete connections; some should have read-only browse; ops needs an admin panel to fix bad rows without a psql session. Requirements:

1. **Per-resource-type permissions** (chosen granularity). Not global roles like "admin/editor/viewer" and not per-object ownership — a middle ground where each resource type has its own verbs.
2. **FastAdmin at `/admin`** for direct table access, sharing the `User` table from plan 022.
3. Enforced on **every API route**, not just the ones we remember.

## Architecture

### Permission model

A **permission** is a `(resource, action)` pair: `pipeline:read`, `pipeline:write`, `pipeline:delete`, `pipeline:trigger`, `source:read`, `source:write`, `source:delete`, `destination:*`, `connection:*` (read/write/delete/test), `run:read`, `run:delete`, `user:*` (admin surface).

Users have a set of **roles**. Roles carry a set of permissions. This is standard RBAC — kept intentionally simple (no permission inheritance, no scopes, no groups).

### Data model

```python
class Role(SQLModel, table=True):
    __tablename__ = "roles"
    id: str = SMField(primary_key=True)
    name: str = SMField(sa_column=Column(Text, unique=True))
    permissions: list[str] = SMField(
        default_factory=list, sa_column=Column(ARRAY(Text), nullable=False)
    )

class UserRoleLink(SQLModel, table=True):
    __tablename__ = "user_roles"
    user_id: str = SMField(foreign_key="users.id", primary_key=True)
    role_id: str = SMField(foreign_key="roles.id", primary_key=True)
```

Permissions live as a Postgres `TEXT[]` on `Role` rather than a separate `permissions` table. Rationale: the permission catalog is code-defined (a `Literal[...]` enum), not user-editable. A separate table would add joins with no runtime value. Validation happens in the API layer against the enum.

`User` gains a `roles: list[Role]` relationship (lazy-loaded per request).

### Seed roles

Migration seeds three canned roles so a fresh install is usable:
- `admin` — every permission
- `editor` — `*:read`, `*:write`, `pipeline:trigger`, `connection:test`
- `viewer` — `*:read`

Bootstrap: the first registered user is auto-assigned `admin` (matches the plan 022 `DTE_ALLOW_REGISTRATION` flow). Subsequent users default to no roles — admin assigns via `/admin` or the API.

### Enforcement — one dependency, applied on every route

`backend/dte/security/permissions.py`:
```python
Permission = Literal[
    "pipeline:read","pipeline:write","pipeline:delete","pipeline:trigger",
    "source:read","source:write","source:delete",
    "destination:read","destination:write","destination:delete",
    "connection:read","connection:write","connection:delete","connection:test",
    "run:read","run:delete",
    "user:read","user:write","user:delete",
]

def requires(perm: Permission):
    async def dep(user: User = Depends(get_current_user)) -> User:
        if not user_has_perm(user, perm):
            raise HTTPException(403, f"missing permission: {perm}")
        return user
    return dep
```

Attach at the individual route level. Example in `pipelines.py`:
```python
@router.get("", dependencies=[Depends(requires("pipeline:read"))])
async def list_pipelines(...): ...

@router.post("", dependencies=[Depends(requires("pipeline:write"))])
async def create_pipeline(...): ...

@router.delete("/{id}", dependencies=[Depends(requires("pipeline:delete"))])
async def delete_pipeline(...): ...

@router.post("/{id}/trigger", dependencies=[Depends(requires("pipeline:trigger"))])
async def trigger_pipeline(...): ...
```

Router-level `Depends(get_current_user)` from plan 022 stays; `requires(...)` adds per-route.

### Test-fixture safety net

`backend/tests/test_route_permissions.py` — introspects the app's route table, and for every non-`/auth/*` route asserts that its dependency stack includes a `requires(...)` call. Fails CI if someone adds a route without a permission gate. This is the actual mechanism that makes "every API route" enforceable.

### FastAdmin at `/admin`

FastAdmin binds to SQLAlchemy mapped classes. Because plan 021 makes every entity SQLModel (which is SQLAlchemy underneath), FastAdmin binds directly to the SQLModel classes in `dte/models/pipeline.py` and `dte/models/user.py` — no separate `dte/store/models.py` needed (plan 018's Task 1 approach becomes obsolete).

Setup in `backend/dte/admin/`:
- `bootstrap.py` — register `ModelAdmin` subclasses for `Pipeline`, `Source`, `Destination`, `Connection`, `Run`, `User`, `Role`
- Auth: FastAdmin uses its own session-cookie login form. We wire its login callback to the same `User` table via a small adapter (verify password with `passlib`; check the user has `user:*` permissions before granting admin access).
- Mount: `app.mount("/admin", admin_app)` in `main.py`, gated by `DTE_ADMIN_ENABLED=true` (default off).

### Credential safety in admin

`Connection.credentials` and `Connection.credentials_encrypted` are both marked **read-only and hidden** in FastAdmin. Editing creds routes through the app UI so the injected `SecretResolver` handles encryption. Display: `"••• hidden — edit via app UI"`.

### Async or sync engine for FastAdmin

FastAdmin's SQLAlchemy provider is sync-only as of writing. Bootstrap constructs a sync engine from `DATABASE_URL` by stripping `+asyncpg` (same pattern as `alembic env.py`). This is a separate engine from the app's async one — fine, they don't share sessions.

## Alembic migration

`011_rbac.py`:
```sql
CREATE TABLE roles (
  id text PRIMARY KEY,
  name text NOT NULL UNIQUE,
  permissions text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_roles (
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id text NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);

-- Seed canned roles
INSERT INTO roles (id, name, permissions) VALUES
  ('admin',  'admin',  ARRAY[...every perm...]),
  ('editor', 'editor', ARRAY[...]),
  ('viewer', 'viewer', ARRAY[...]);
```

## Files changed / added

Added:
- `backend/dte/models/user.py` — add `Role`, `UserRoleLink`, `User.roles` relationship
- `backend/dte/security/permissions.py` — `Permission` enum, `requires(...)`, `user_has_perm(...)`
- `backend/dte/admin/{bootstrap.py, model_admins.py, auth.py}`
- `backend/alembic/versions/011_rbac.py`
- `backend/tests/test_route_permissions.py` — introspection test
- `backend/tests/test_rbac.py` — matrix: for each role, hit every route, assert 200/403 as expected

Changed:
- `backend/dte/api/main.py` — mount FastAdmin (if enabled)
- `backend/dte/api/routes/*.py` — add `Depends(requires(...))` per route
- `backend/dte/api/routes/auth.py` — on register, auto-assign `admin` role if `SELECT count(*) FROM users = 1`
- Optional new routes: `POST /api/users/{id}/roles`, `DELETE /api/users/{id}/roles/{role_id}` (gated by `user:write`)
- `frontend/src/components/app-sidebar.tsx` — hide nav items the current user lacks permission for (read `user.permissions` from `/auth/me`)
- `docker-compose.yml` — set `DTE_ADMIN_ENABLED=true`, `DTE_ADMIN_SECRET_KEY=...`
- `backend/pyproject.toml` — add `fastadmin`

## Tasks

### Task 1 — RBAC data + `requires` dep  (branch `feature/rbac-core`)

Role model, migration, seed, permission enum, `requires()` dep, `user_has_perm()`. No routes changed yet.

### Task 2 — apply guards to every route  (branch `feature/rbac-guards`)

Add `Depends(requires(...))` to every route in pipelines/runs/sources/destinations/connections/schema. Add the introspection test that fails CI if any route is un-gated. Add the RBAC matrix test.

### Task 3 — bootstrap flow + user/role management API  (branch `feature/rbac-users-api`)

First-user auto-admin. Endpoints to list users, assign/revoke roles. Frontend nav-item hiding based on `/auth/me` permissions.

### Task 4 — FastAdmin mount  (branch `feature/fastadmin`)

Register ModelAdmins, wire FastAdmin login to our User table, mask connection credentials. Gate behind `DTE_ADMIN_ENABLED`. Verify docker-compose can log into `/admin` and browse tables.

## Verification

```bash
cd backend
uv run alembic upgrade head
uv run pytest -x                        # includes the route-permission introspection test

# manual E2E
docker compose up -d --build
# register first user (auto-admin)
curl -X POST localhost:8001/api/auth/register -d '{"email":"admin@x.com","password":"pw"}' -H 'content-type: application/json'
TOKEN=$(curl -s -X POST localhost:8001/api/auth/login -d '{"email":"admin@x.com","password":"pw"}' -H 'content-type: application/json' | jq -r .access_token)

# register a viewer
curl -X POST localhost:8001/api/users -H "Authorization: Bearer $TOKEN" -d '{"email":"v@x.com","password":"pw"}' -H 'content-type: application/json'
# assign viewer role
curl -X POST localhost:8001/api/users/<v_id>/roles -H "Authorization: Bearer $TOKEN" -d '{"role_id":"viewer"}' -H 'content-type: application/json'

# viewer can list, cannot create
V_TOKEN=$(curl -s -X POST localhost:8001/api/auth/login -d '{"email":"v@x.com","password":"pw"}' -H 'content-type: application/json' | jq -r .access_token)
curl -H "Authorization: Bearer $V_TOKEN" localhost:8001/api/pipelines           # 200
curl -H "Authorization: Bearer $V_TOKEN" -X POST localhost:8001/api/pipelines   # 403

# FastAdmin
open http://localhost:8001/admin
```

Success criteria:
- The route-permission introspection test passes (every non-auth route has a `requires(...)`)
- The RBAC matrix test passes (each role gets 200/403 as designed on every route)
- `/admin` login works with the same email/password as the API, and only users with `user:*` perms can log in
- Connection credentials are hidden in FastAdmin

## Out of scope

- Per-object ownership (`Pipeline.owner_id`) — deliberate; per-resource-type was the chosen granularity
- Custom role creation via UI — admins create roles via the API / `/admin` for now
- Audit log
- API keys / service accounts (JWT-only for both humans and machines in this iteration)

## Supersedes

Plan 017 (FastAdmin) — its "add ModelAdmins" mechanic is absorbed here as Task 4. Plan 017's "auth via `admin_users` table" is replaced by the shared `User` table from plan 022.
