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

See plans/032-batched-alembic-backfills.md.
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
    """Run UPDATE in bounded batches. Returns total rows written.

    Each batch runs in its own AUTOCOMMIT transaction — the outer Alembic
    transaction is bypassed so committed batches survive a mid-run kill.
    Idempotence relies on ``where_clause`` continuing to select only rows
    that still need updating; write it accordingly.

    ``FOR UPDATE SKIP LOCKED`` lets concurrent OLTP writers coexist —
    rows locked by app queries are skipped this batch and picked up next.
    """
    # We need AUTOCOMMIT so each batch is committed independently — a killed
    # migration leaves already-committed batches on disk.
    # op.get_bind() returns the connection inside the enclosing Alembic
    # transaction; calling .execution_options() on it raises InvalidRequestError
    # because a transaction is already open (autobegin or explicit).
    # We open a separate AUTOCOMMIT connection via the engine instead.
    #
    # IMPORTANT CAVEAT: if the calling migration has un-committed DDL (e.g.
    # ALTER TABLE … ADD COLUMN run earlier in the same alembic step), the new
    # AUTOCOMMIT connection won't see those changes because transactional DDL
    # hasn't committed yet.  In that case we fall back to running the UPDATE
    # inside the existing Alembic transaction (no per-batch isolation guarantee,
    # but correct for fresh databases where the rows to update are zero anyway).
    alembic_conn = op.get_bind()
    engine = alembic_conn.engine

    # Probe: can a fresh connection see the target table?
    def _table_visible_on_new_conn() -> bool:
        try:
            with engine.connect() as probe:
                probe.execute(
                    text(f"SELECT 1 FROM {table} LIMIT 0")
                )
            return True
        except Exception:
            return False

    if _table_visible_on_new_conn():
        raw_conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        conn = raw_conn
        _owns_conn = True
    else:
        # DDL not yet committed — fall back to the existing Alembic connection.
        # Batches won't be individually committed, but this path is only hit
        # when the table was just created in this migration (zero rows to update).
        log.info(
            "batched_update %s: table not yet visible on new connection "
            "(DDL uncommitted); running within existing Alembic transaction.",
            table,
        )
        conn = alembic_conn
        _owns_conn = False

    total = 0
    batch = 0
    started = time.monotonic()

    try:
        while True:
            if max_batches is not None and batch >= max_batches:
                log.info("batched_update %s: hit max_batches=%s", table, max_batches)
                break

            result = conn.execute(
                text(
                    f"UPDATE {table} "
                    f"SET {set_clause} "
                    f"WHERE {key_column} IN ("
                    f"  SELECT {key_column} FROM {table} "
                    f"  WHERE {where_clause} "
                    f"  LIMIT :batch_size "
                    f"  FOR UPDATE SKIP LOCKED"
                    f")"
                ),
                {"batch_size": batch_size},
            )

            n = result.rowcount or 0
            if n == 0:
                break
            total += n
            batch += 1
            log.info(
                "batched_update %s: batch %d wrote %d rows (total %d)",
                table,
                batch,
                n,
                total,
            )
    finally:
        if _owns_conn:
            raw_conn.close()

    elapsed = time.monotonic() - started
    log.info(
        "batched_update %s done: %d rows in %d batches (%.1fs)",
        table,
        total,
        batch,
        elapsed,
    )
    return total
