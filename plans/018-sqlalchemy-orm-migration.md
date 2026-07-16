# Plan 018 — migrate stores to SQLAlchemy declarative ORM

## Problem

`backend/dte/store/postgres.py` uses SQLAlchemy purely as a connection layer: every method is a `text("...")` raw SQL string, and the tables are defined only in Alembic `op.execute("CREATE TABLE ...")` DDL. That works but it:

- forces us to hand-maintain drift-prone models if we bolt anything on that expects ORM classes (plan 017 hit this — FastAdmin needs mapped classes)
- gives us no typed row access — every method reshapes `dict(row)` and stringifies timestamps by hand (see `PostgresRunStore.get`)
- makes it easy for the raw INSERT column list to silently drift from the migration (`sources.table_name` ↔ dict key `table` gets remapped in three places)
- rules out `session.get(Pipeline, id)`, `select().where()`, relationship loading, etc.

Introducing declarative models purely for a future admin panel duplicates the schema. Better to migrate the stores.

## Architecture change

### Boundaries preserved

- **Store Protocols in `dte/store/base.py` are unchanged.** They return `dict`/`str`/`bool` — plain Python. Callers (routes, executor task) keep working. This plan is a pure internal refactor of `PostgresPipelineStore` / `PostgresRunStore` / `PostgresSourceStore` / `PostgresDestinationStore` / `PostgresConnectionStore`.
- **Alembic remains the source of truth for schema.** Models mirror what migrations create. No `Base.metadata.create_all()`, ever. A CI-level test reflects the live DB and diffs it against the mapped models to catch drift.
- **`FakeStore` implementations in `tests/fakes.py` don't change** — they already speak dicts against the Protocol.

### JSONB handling

Three JSONB columns exist today: `pipelines.definition`, `sources.config`, `destinations.config`. Map each with `Mapped[dict] = mapped_column(JSONB)` — SQLAlchemy round-trips dicts natively. No custom TypeDecorator. Do **not** try to type them as Pydantic models at the ORM layer — the models already parse on the way in through the API layer, and the store contract is `dict`.

### Timestamps

`runs.started_at` / `finished_at` are `TIMESTAMPTZ`. Model them as `Mapped[datetime | None]`. The store's `get` / `list_for_pipeline` still ISO-format to string at the boundary (Protocol contract stays wire-shaped). The `BEFORE UPDATE` trigger from migration 003 keeps writing `finished_at` — the ORM `update` does not need to set it; it just SETs `status` and reads the trigger-populated value back if needed.

### Session pattern

Keep the `async_sessionmaker` injection. Inside each method, `async with self._factory() as s: ...` unchanged. Replace `text(...)` with `session.get(Model, id)`, `select(Model)`, `s.merge(instance)` for upsert-style save (or `insert(...).on_conflict_do_update(...)` from `sqlalchemy.dialects.postgresql` for the `updated_at = now()` case — `merge` doesn't touch it). Prefer the `insert().on_conflict_do_update()` form for parity with today's SQL.

### The one subtle piece — connections

`PostgresConnectionStore` encrypts/decrypts via the injected `SecretResolver`. That stays outside the ORM. The mapped `Connection.credentials_encrypted: Mapped[bytes]` holds the ciphertext; the store method wraps `resolver.encrypt(...)` / `resolver.decrypt(...)` around it exactly as today. Do not add a TypeDecorator that transparently encrypts — the resolver is injected per-store, not per-engine.

## Tasks

Each task on its own worktree per CLAUDE.md.

### Task 1 — declarative Base + models, no wiring

Branch: `feature/orm-models`

- add `backend/dte/store/models.py` with `Base = declarative_base()` and one `Mapped`-annotated class per existing table: `Pipeline`, `Run`, `Source`, `Destination`, `Connection`
- match columns exactly to what migrations 001–005 create — same names, types, nullability, defaults, PKs
- add `backend/tests/integration/test_orm_schema_drift.py`: reflect the live DB (skip if `DATABASE_URL` unset), and for every mapped class assert (a) table exists, (b) every column name in the model exists in the reflected table with matching type family (text→text, jsonb→jsonb, timestamp→timestamp, bytea→bytea)
- **do not import `models.py` from any store yet** — this task is purely additive

### Task 2 — migrate `PostgresPipelineStore` and `PostgresRunStore`

Branch: `feature/orm-pipeline-run-stores`

- rewrite both stores in `dte/store/postgres.py` to use ORM: `session.get(Pipeline, id)`, `select(Pipeline).order_by(...).limit(...)`, `insert(Pipeline).values(...).on_conflict_do_update(...)`, etc.
- run `uv run pytest -x` — every existing integration test in `tests/integration/test_store_postgres.py` must pass unmodified. That's the acceptance criterion.
- keep the ISO-string timestamp shaping at the store boundary

### Task 3 — migrate `PostgresSourceStore` and `PostgresDestinationStore`

Branch: `feature/orm-source-dest-stores`

- same pattern
- verify the `table` ↔ `table_name` remapping is preserved (it happens once in the store now, not three times)

### Task 4 — migrate `PostgresConnectionStore`

Branch: `feature/orm-connection-store`

- ORM under the hood; resolver stays wrapped around `credentials_encrypted` at the store layer
- verify masking behavior in `list` — must never call `resolver.decrypt`

### Task 5 — cleanup + docs

Branch: `feature/orm-cleanup`

- drop the now-unused `from sqlalchemy import text` and `import json` if all callers gone
- update the **Store / database** section of `CLAUDE.md`: note that stores are ORM-backed but Alembic is still authoritative for schema, and point at the drift-check test
- if any test relies on `text()` behavior specific to the old code, note it

## Files changed / added

Added:
- `backend/dte/store/models.py`
- `backend/tests/integration/test_orm_schema_drift.py`

Changed:
- `backend/dte/store/postgres.py` (full rewrite, class-by-class across tasks 2–4)
- `CLAUDE.md` (Store / database section)

Deleted: none. Migrations, Protocols, fakes, routes, and the executor stay put.

## Out of scope

- Any schema change (no new columns, no new tables, no dropping `table_name`-vs-`table` name mismatch — that stays a store-layer concern)
- Relationships between models (e.g. `Pipeline.runs`) — not needed until a caller wants them; adding them now is speculative
- Switching Alembic to autogenerate from models — Alembic-authoritative is deliberate; leave it
- Migrating the `FakeStore` implementations to use the ORM against SQLite or similar — they stay in-memory dict-based

## Sequencing with plan 017

Land 018 first, then plan 017 collapses into: register `ModelAdmin` classes against `dte/store/models.py`, add auth, mount at `/admin`. The drift-check test that plan 017 needed becomes free — it already lives here.
