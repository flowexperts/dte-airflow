## Store / database

**Postgres-only** — there is no in-memory production path. `DATABASE_URL` must be set; getters in `dte/api/deps.py` raise `RuntimeError` if it's missing. Tests inject `Fake*Store` implementations from `tests/fakes.py` via `app.dependency_overrides` (an autouse conftest fixture attaches them, plus a pre-seeded `local_fs` connection so most tests don't need boilerplate). Both Postgres stores hold a session factory (not a live session) so the singleton is safe across FastAPI requests and the background `asyncio.create_task` in `trigger_pipeline`.

Under Docker Compose, `DATABASE_URL=postgresql+asyncpg://dte:dte@postgres:5432/dte` is set on the backend service. The compose command runs `alembic upgrade head` first (using a synced URL derived by stripping `+asyncpg`) and then execs uvicorn. Pipelines persist across `docker compose restart` via the `pgdata` volume.

Postgres integration tests (`tests/integration/test_store_postgres.py`) are skipped automatically when `DATABASE_URL` is unset. When enabled, they use an `async_sessionmaker` fixture and pass it to the store constructors — mirror this pattern in any new integration test.

### Alembic backfills

Any backfill that could touch > 100k rows **must** use `dte.alembic_util.batched_update` — never a bare `UPDATE ... SET ...` or a `for row in session.query(...)` loop inside a migration. The helper runs each batch in its own AUTOCOMMIT transaction so a killed migration leaves committed batches on disk, and uses `FOR UPDATE SKIP LOCKED` to coexist with concurrent OLTP writers. See `plans/032-batched-alembic-backfills.md`.

### Model + store pattern (SQLModel)

Every Pydantic-modelled persisted entity — `Pipeline`, `Source`, `Destination`, `Connection` — is a **two-class** pair in `dte/models/pipeline.py`:

- `XxxBase(SQLModel)` — API/domain fields + Pydantic validators. `id: str` is required here so FastAPI raises 422 on missing. Carries the API-strict Literal types (e.g. `connection_type: ConnectionType`, `source_type: SourceKind`) — Pydantic rejects unknown values at the edge. Routes bind POST/PUT bodies to `XxxBase`.
- `Xxx(XxxBase, table=True)` — persistence identity (overrides `id: str = SMField(primary_key=True)`), timestamp columns, and Literal overrides to plain `str` (SQLModel 0.0.39 can't map Literal to a SA column). Stores save and return typed `Xxx` instances.

Back-compat aliases `XxxCreate = XxxBase` are kept for one release so existing migration scripts don't break.

**`EncryptedJSON` TypeDecorator** (`dte/secrets/encrypted_json.py`) — used for `Connection.credentials`. Maps the logical Python `dict` to a BYTEA column (`credentials_encrypted`), transparently calling `get_secret_resolver().encrypt()` on write and `.decrypt()` on read. `PostgresConnectionStore` needs no `SecretResolver` injection — encryption happens at the column level. Physical column name unchanged; no migration required.

**SQLModel 0.0.39 gotchas hit by this codebase:**

- `Literal[...]` types on a `table=True` class break the metaclass (it calls `issubclass(Literal, Enum)`). Workaround: keep the strict `Literal` on `Base` for API validation; override with `str` + an explicit `sa_column=Column(Text, ...)` on the table class. Both classes now live together without a third `Create` class.
- `table=True` construction skips Pydantic validators. For hydrated instances that need post-load narrowing (e.g. `Destination.config` narrowed from a raw JSONB dict to the discriminated `OutputTarget` union), the store calls an explicit method — `Destination.narrow_config()` uses `TypeAdapter(OutputTarget).validate_python(...)` + `object.__setattr__` to bypass SA instrumentation. Do NOT rely on validators to fire on ORM hydration. `Connection.credentials` no longer needs this because `EncryptedJSON` handles the round-trip at the TypeDecorator level.

**Store shape.** Every `Postgres*Store` (except `PostgresRunStore`) uses the same three-verb ORM template — see `PostgresPipelineStore` as the canonical example:

- `get(id)` → `session.get(Xxx, id)`
- `save(base)` → `pg_insert(Xxx).values(**base.model_dump(exclude={timestamps})).on_conflict_do_update(...)` — the `on_conflict_do_update` form is required (not `session.merge`) because `updated_at` has an `onupdate=func.now()` server default that `merge` won't trigger
- `list(...)` → `select(Xxx).order_by(Xxx.created_at.desc())`

Fakes (`tests/fakes.py`) store typed `Xxx` instances and accept `XxxBase | Xxx | dict` at `save()` (dict for legacy migration-script compat). New tests should always pass typed `XxxBase` instances.

### Step validation is strict on write, lenient on read

`PipelineBase` — what POST/PUT bind — parses every step through
`_STEP_MODELS`, so an unknown op or a bad config is rejected at save.
`Pipeline` (the table class, and the **response** model FastAPI re-validates
on every read) only checks that a step is a dict naming an op.

The asymmetry is the point. A row written by a newer build — or by a branch
since rolled back, or by another worktree sharing the `dte_pgdata` volume —
raised inside response validation and returned a 500 for **`GET
/api/pipelines` as a whole**: every other pipeline in the list vanished, and
the only clue was `('response', 1)` naming a step index. Version skew is
normal; losing the collection to one row from the future is not. An unknown
op still fails, per step, at compile — which is where it is actionable.

The override is `mode="before"`. An after-validator on a `table=True` class
touches instrumented attributes, and under `model_validate` the instance has
no `_sa_instance_state` yet.
