# Plan 030 — Multi-tenant isolation

Covers P2 #24 from `plans/027-p0-p4-status-ladder.md`.

## Threat model

Today DTE assumes a single tenant. If we onboard a second customer without changes:

1. **Cross-tenant read via list endpoints** — `GET /api/pipelines` returns every row; JWT sub identifies the user but no row-level filter runs.
2. **Cross-tenant read via direct id** — `GET /api/pipelines/{id}` returns any known id; RBAC (plan 023) only gates the verb, not the resource ownership.
3. **Cross-tenant write via referential spoofing** — a valid user of tenant A can POST a pipeline whose `source_id` points at a source owned by tenant B, then trigger it and exfiltrate the target's data.
4. **Shared encryption blast radius** — one `DTE_SECRETS_KEY` encrypts every connection blob. Key compromise = every tenant's credentials disclosed.

## Tenant model

Add `tenant_id: str` to every user-owned entity:

- `pipelines`, `sources`, `destinations`, `connections`, `runs`, `run_events`, `run_quality_results`, `lookup_tables`, `credential_decrypt_audit` (plan for #36), `users`.

`Tenant` itself is a new table:

```sql
CREATE TABLE tenants (
    id text PRIMARY KEY,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

JWT payload gains a `tenant` claim alongside `sub` and `roles`. Login flow chooses tenant either from the user's default (`users.tenant_id`) or from a `POST /api/auth/switch-tenant` endpoint (later — MVP is one-tenant-per-user).

## Isolation strategy — **Postgres RLS**

Options considered:

| Approach | Pro | Con |
| - | - | - |
| Filter-in-store (`WHERE tenant_id = :t` in every query) | Cheap to add | Error-prone: one missed `WHERE` leaks everything. Devs will forget. |
| **Postgres RLS** (recommended) | DB-enforced. No missed `WHERE` ever leaks. Works even for direct psql access. | Requires per-request session variable + RLS policies per table. Slight query planner impact. |
| Schema-per-tenant | Strongest isolation | Migrations run per tenant. Cross-tenant admin queries painful. Overkill for our scale. |

We pick **RLS**. Blast radius of a coding mistake shrinks from "any missed filter" to "manually bypassing RLS with `SET LOCAL row_security = off`", which reviewers can grep for.

### RLS wiring

Per table:

```sql
ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipelines FORCE ROW LEVEL SECURITY;    -- forces even the table owner

CREATE POLICY tenant_isolation ON pipelines
    USING (tenant_id = current_setting('dte.tenant_id')::text);
```

`current_setting('dte.tenant_id')` is a per-transaction session variable. Set it at the start of every request in the SQLAlchemy engine's `connect` event or in a FastAPI middleware wrapping `AsyncSession`:

```python
@event.listens_for(engine.sync_engine, "connect")
def _set_tenant(dbapi_conn, _):
    # cleared at end of txn; set fresh on each request
    pass

# in middleware:
tenant = current_user.tenant_id
await session.execute(text("SET LOCAL dte.tenant_id = :t"), {"t": tenant})
```

The background `asyncio.create_task` in `_execute_pipeline` gets the tenant from the run row (looked up before the task starts) and sets it on its own session.

Admin endpoints (super-user / cross-tenant ops) run with `SET LOCAL row_security = off` — grep-detectable, code-reviewed.

## Per-tenant secrets

Store one Fernet key per tenant. New table:

```sql
CREATE TABLE tenant_secret_keys (
    tenant_id  text PRIMARY KEY REFERENCES tenants(id) ON DELETE RESTRICT,
    key_fernet bytea NOT NULL,          -- wrapped by DTE_ROOT_KEY
    rotated_at timestamptz NOT NULL DEFAULT now()
);
```

The root key `DTE_ROOT_KEY` unwraps per-tenant keys on demand. `FernetSecretResolver` grows a `get_key(tenant_id)` method; `EncryptedJSON.process_bind_param` uses the current tenant's key.

Rotation runbook (`docs/runbooks/secrets-rotation.md`) picks up a new `--tenant <id>` flag routed through `rotate_secrets_key.py`.

## Migration

- Alembic `015_tenant_id.py`:
  - `CREATE TABLE tenants`.
  - `ALTER TABLE <every_user_owned_table> ADD COLUMN tenant_id text NOT NULL DEFAULT 'default'`, then drop the default.
  - Backfill `INSERT INTO tenants (id, name) VALUES ('default', 'Default tenant')`.
- Alembic `016_rls_policies.py`: enable RLS + policies per table.
- Alembic `017_tenant_secret_keys.py`: new table + `INSERT INTO tenant_secret_keys` from current `DTE_SECRETS_KEY` (via a one-shot script).

## Testing

- **Isolation test** (`tests/integration/test_tenant_rls.py`): two users, two tenants. User A cannot see user B's pipelines even with the direct id. Attempting a POST that references B's source id 404s (the source lookup is filtered by RLS, so it appears not to exist). Cross-tenant DELETE 404s.
- **Fake store** grows tenant awareness: `Fake*Store.get(id, tenant_id)`.
- Scenario suite: `client` fixture provides a tenant + user; a second `client_b` fixture is used in cross-tenant tests.

## Rollout

- **`DTE_MULTI_TENANT_ENABLED` flag** — default off in v1. When off, `tenant_id` defaults to `"default"` on all writes and RLS policies allow all.
- Ship migrations independently of the flag flip.
- Flip to `on` after: (1) all tests pass under both flag states, (2) the isolation test above green in CI for two consecutive weeks.
- Remove the flag two releases later.

## Task list

- `feature/tenant-model` — schema + migrations + tenant claim in JWT.
- `feature/tenant-rls` — RLS policies + session variable middleware.
- `feature/tenant-secrets` — per-tenant Fernet keys + root-key wrap.
- `feature/tenant-tests` — isolation tests + fake-store update.

## Non-goals

- Cross-region isolation (data residency requirements are a separate concern).
- Tenant self-service admin UI. Ops provisions tenants via a script for v1.
- Tenant-scoped rate limits (slowapi is per-IP today; add per-tenant when metrics show it matters).
