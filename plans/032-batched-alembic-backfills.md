# Plan 032 — Batched Alembic backfill helper

Covers P3 #34 from `plans/027-p0-p4-status-ladder.md`.

## Problem

`backend/alembic/versions/008_*.py` does an unbatched `UPDATE` across every existing pipeline row to convert legacy `__` field refs to dot syntax. Fine at today's row count (< 100). At 10M rows it would:

1. Hold `ROW EXCLUSIVE` on `pipelines` for the entire migration.
2. Generate one WAL entry per touched row — bloating the WAL until checkpoint.
3. Run inside Alembic's own transaction, so any error rolls back the whole thing including the schema change that preceded it.

We need a reusable helper for any future backfill that could touch a big table.

## Helper

New file `backend/dte/alembic_util.py`:

```python
"""Batched-update helper for Alembic backfills.

Usage inside an Alembic revision:

    from dte.alembic_util import batched_update

    def upgrade():
        # ... schema change ...
        batched_update(
            op,
            table="pipelines",
            set_clause="config = jsonb_set(config, '{version}', '\"2\"')",
            where_clause="config->>'version' IS NULL",
            batch_size=5000,
        )
"""
from __future__ import annotations

import logging
import time

from alembic.operations import Operations
from sqlalchemy import text

log = logging.getLogger("dte.alembic")


def batched_update(
    op: Operations,
    *,
    table: str,
    set_clause: str,
    where_clause: str,
    batch_size: int = 5000,
    key_column: str = "id",
    max_batches: int | None = None,
) -> int:
    """Run UPDATE in bounded batches. Returns the total row count.

    Each batch runs in its own autocommit-mode transaction — the outer
    Alembic transaction is bypassed with `.execution_options(isolation_level=
    "AUTOCOMMIT")`. If an operator kills the migration mid-way, previously
    committed batches stay; the where clause guarantees idempotence.
    """
    conn = op.get_bind().execution_options(isolation_level="AUTOCOMMIT")
    total = 0
    batch = 0
    started = time.monotonic()

    while True:
        if max_batches is not None and batch >= max_batches:
            log.info("batched_update: hit max_batches=%s, stopping", max_batches)
            break

        result = conn.execute(text(f"""
            UPDATE {table}
            SET {set_clause}
            WHERE {key_column} IN (
                SELECT {key_column} FROM {table}
                WHERE {where_clause}
                LIMIT :batch_size
                FOR UPDATE SKIP LOCKED
            )
        """), {"batch_size": batch_size})

        n = result.rowcount or 0
        if n == 0:
            break
        total += n
        batch += 1
        log.info("batched_update %s: batch %d wrote %d rows (total %d)",
                 table, batch, n, total)

    elapsed = time.monotonic() - started
    log.info("batched_update %s done: %d rows in %d batches (%.1fs)",
             table, total, batch, elapsed)
    return total
```

### Why `SKIP LOCKED`

Lets long-running batches coexist with concurrent OLTP writers on the same table. A row locked by an app query is simply skipped this batch and picked up next batch. Because the `where` clause is the filter, skipped rows are re-detected until they're free.

### Why `AUTOCOMMIT` isolation

Alembic wraps `upgrade()` in a single transaction by default. That defeats the purpose of batching — the WAL never commits until the end. We opt out per-batch and rely on the `where` clause for idempotence.

## Migration `008` rewrite

Reduce the old unbatched loop to:

```python
from dte.alembic_util import batched_update

def upgrade():
    # ... existing schema change ...
    batched_update(
        op,
        table="pipelines",
        set_clause="config = <the transform>",
        where_clause="<the same filter that used to select-then-loop>",
        batch_size=1000,
    )
```

The behaviour delta is nil at current row counts. The value is that any future backfill can copy this pattern.

## Guidance addition to `CLAUDE.md`

Under the Migrations section:

> **Backfills over > 100k rows must use `dte.alembic_util.batched_update`.** Never write a `for row in session.query(...)` loop or an unbounded `UPDATE ... SET ...` inside a migration.

## Testing

- Unit test with SQLite (in-memory) proves the loop terminates and returns the correct count.
- Integration test (real Postgres, opt-in via DATABASE_URL): create a table with 250k rows, run `batched_update` with `batch_size=10000`, assert 250k updated in 25 batches, assert other transactions can read concurrently.

## Task list

- One branch: `feature/batched-backfill-helper`.
- Files: new `backend/dte/alembic_util.py`; test at `backend/tests/unit/test_alembic_util.py`; optional integration test; rewrite of migration `008`; CLAUDE.md paragraph.

## Non-goals

- Online schema-change tooling (pg_repack, gh-ost). Separate concern.
- Async iteration (Alembic runs sync — the helper stays sync).
- Progress tracking beyond log lines.
