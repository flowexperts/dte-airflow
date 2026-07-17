# Plan 021 — SQLModel for Source, Destination, Connection

## Problem

Plan 018 was scoped as "internal store refactor, Protocols unchanged". Task 1 of 018 (commit `3ee4358`) went further and converted `Pipeline` into a single SQLModel-based class hierarchy (`PipelineBase` + `Pipeline(table=True)` + `PipelineCreate`), collapsing the dict boundary between the API and the store. Only Pipeline landed. `Source`, `Destination`, and `Connection` are still plain `BaseModel`s (`backend/dte/models/pipeline.py:138,267,488`) with hand-rolled `text(...)` SQL stores (`backend/dte/store/postgres.py:119–319`).

The goal is that **every DB read and write flows through a SQLModel** — no separate Pydantic-for-API vs. dict-in-store split. This plan finishes what commit `3ee4358` started for the other three entities. It is a prerequisite for plans 022 (auth) and 023 (RBAC + FastAdmin), which also need SQLModel classes to bind against.

## Architecture change

Mirror the pattern already in `models/pipeline.py:505–532` for each of the three entities:

- `XxxBase(SQLModel)` — domain fields with strict Pydantic validators (used for API validation)
- `Xxx(XxxBase, table=True)` — adds `id`, `created_at`, `updated_at`
- `XxxCreate(XxxBase)` — adds required `id: str` for POST payloads

Store Protocols in `dte/store/base.py` change return types from `dict` to typed instances. API routes stop calling `Source(**raw)` / `Destination(**raw)` / `Connection(**raw)` — the store already returns typed objects.

### Connection credentials — encryption

Two options considered:

- **A. `EncryptedJSON` TypeDecorator** on `credentials` — clean uniform model, but ties encryption to the SQLAlchemy engine (not the injectable `SecretResolver`).
- **B. Split fields** — `credentials_encrypted: bytes` on the table, `credentials: dict` on `ConnectionBase`/`ConnectionCreate`, store translates in `save`/`get`. Preserves the plan-018 seam ("resolver is injected per-store, not per-engine").

**Chose B.** Testing already depends on swapping resolvers via `Fake*Store`; a TypeDecorator would either force test setup to reach into engine internals or lose that flex. The extra 6 lines in the store are worth keeping the seam.

Concretely:
```python
class ConnectionBase(SQLModel):
    connection_type: ConnectionType
    credentials: dict = SMField(default_factory=dict)   # NOT persisted
    # keep the existing @model_validator(mode="after") that validates
    # credentials against the dlt spec class

class Connection(ConnectionBase, table=True):
    __tablename__ = "connections"
    id: str = SMField(primary_key=True)
    credentials_encrypted: bytes = SMField(sa_column=Column(LargeBinary, nullable=False))
    created_at / updated_at   # same as Pipeline

    # `credentials` is on Base and therefore inherited, but we mark it
    # non-persistent by setting sa_column=None (SQLModel default: attribute
    # only, not a mapped column). Guaranteed by omitting it from `__table__`.

class ConnectionCreate(ConnectionBase):
    id: str
```

Store `save`:
```python
async def save(self, c: Connection) -> None:
    ciphertext = self._resolver.encrypt(c.credentials or {})
    row = Connection(id=c.id, connection_type=c.connection_type,
                     credentials_encrypted=ciphertext)
    # upsert via pg_insert().on_conflict_do_update()
```

Store `get` returns `Connection` with `credentials` populated from `resolver.decrypt(row.credentials_encrypted)`.

### Source

```python
class SourceBase(SQLModel):
    connection_id: str
    source_type: SourceKind
    config: dict = SMField(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    table: str = SMField(sa_column=Column("table_name", Text, nullable=False))
    format: _FileFormat | None = None
    # keep both @model_validator methods: _extract_legacy_format, _validate_config
```

`sa_column=Column("table_name", ...)` preserves the physical column name; no migration needed.

### Destination

```python
class DestinationBase(SQLModel):
    connection_id: str
    config: OutputTarget = SMField(sa_column=Column(JSONB, nullable=False))
```

`OutputTarget` is a discriminated `Annotated[Union[...]]`. SQLModel gives back a raw dict from JSONB on hydration; add a `@model_validator(mode="before")` on `DestinationBase` that runs the discriminator lookup and re-parses `config` into the union. The `dest_type` DB column is denormalised from `config.type` — keep writing it via `@model_validator(mode="after")` for now; drop in a follow-up migration.

## Files changed / added

Changed:
- `backend/dte/models/pipeline.py` — refactor `Source`, `Destination`, `Connection`
- `backend/dte/store/base.py` — Protocol return types → typed models
- `backend/dte/store/postgres.py` — rewrite `PostgresSourceStore`, `PostgresDestinationStore`, `PostgresConnectionStore` (mirror `PostgresPipelineStore` at lines 12–56)
- `backend/dte/store/memory.py` — swap dict storage for typed model storage
- `backend/tests/fakes.py` — `Fake*Store` classes store typed instances
- `backend/dte/api/routes/sources.py` — remove `Source(**raw)` reparse (lines 47, 109)
- `backend/dte/api/routes/destinations.py` — remove `Destination(**raw)` reparse (line 18)
- `backend/dte/api/routes/connections.py` — remove `Connection(**raw)` reparse; move credential masking into list handler

Added:
- `backend/tests/conftest.py` — helpers `make_source(**kw)`, `make_destination(**kw)`, `make_connection(**kw)` that return typed instances with sensible defaults, so tests don't repeat construction

Migrations: none. Column names preserved via `sa_column=Column("table_name", ...)`; `credentials_encrypted BYTEA` reused.

## Tasks (each in its own worktree per CLAUDE.md)

Worktree base is `worktrees/orm-models` (already exists, fast-forwarded to main).

### Task 1 — `Connection` → SQLModel  (branch `feature/orm-connection`)

Smallest of the three. Refactor `Connection`, rewrite `PostgresConnectionStore`, update route + fake + tests. Ship.

### Task 2 — `Source` → SQLModel  (branch `feature/orm-source`)

Same pattern; extra care around `table` ↔ `table_name` column mapping and the two existing `@model_validator`s.

### Task 3 — `Destination` → SQLModel  (branch `feature/orm-destination`)

Discriminated-union `config` re-parse on hydration is the tricky bit — verify all existing destination types round-trip.

### Task 4 — cleanup  (branch `feature/orm-cleanup`)

- Delete `text(...)` imports + `import json` from `postgres.py` (only `PostgresRunStore` should still use them — Run is out of scope)
- Update **Store / database** section of `CLAUDE.md`: all four Pydantic-modeled entities are now SQLModel-backed
- Sweep `tests/` for straggling `dict`-style `store.save(...)` calls

## Verification

```bash
cd backend

# 1. Fast tests
uv run pytest -m "not integration" -x

# 2. Postgres round-trip
DATABASE_URL=postgresql+asyncpg://dte:dte@localhost:5432/dte uv run pytest -x

# 3. End-to-end via docker
docker compose up -d --build
# create connection → source → destination → pipeline → trigger → poll
```

Success criteria:
- No `text(...)` or `json.dumps(...)` in `postgres.py` except in `PostgresRunStore`
- No route calls `Source(**...)` / `Destination(**...)` / `Connection(**...)` on data returned from a store
- `pnpm gen:types` in `frontend/` yields the same `api-types.ts` (wire shape must not change)
- Pipelines persisted by the old dict-store code load and preview successfully

## Out of scope

- `Run` → SQLModel (separate follow-up; runs have DB trigger-managed timestamps that need care)
- Removing the denormalised `dest_type` column
- Frontend changes

## Superseded plans

Plan 018 tasks 2–5 are superseded by this plan — the intent (all stores ORM-backed) is preserved but the mechanism is stronger (SQLModel unifies API + persistence rather than declarative-only ORM alongside separate Pydantic models).
