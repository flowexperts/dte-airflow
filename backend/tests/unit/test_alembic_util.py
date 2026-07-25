"""Unit smoke test for batched_update.

The full behaviour test lives in ``tests/integration/test_alembic_util_pg.py``
because the helper uses Postgres-only ``FOR UPDATE SKIP LOCKED`` semantics.
This unit test only asserts the helper is importable + has the expected
signature. See plans/032-batched-alembic-backfills.md.
"""
from __future__ import annotations

import inspect


def test_batched_update_signature():
    from dte.alembic_util import batched_update

    sig = inspect.signature(batched_update)
    params = sig.parameters
    assert "op" in params
    for kw in ("table", "set_clause", "where_clause"):
        assert params[kw].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["batch_size"].default == 5000
    assert params["key_column"].default == "id"
    assert params["max_batches"].default is None
    assert sig.return_annotation in ("int", int)
