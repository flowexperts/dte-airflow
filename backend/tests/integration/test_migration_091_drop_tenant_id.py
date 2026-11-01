"""Migration 091 drops `tenant_id` and keeps names unique; downgrade restores it.

Skipped when DTE_DATABASE_URL is unset. Leaves the DB at head.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration

DTE_DATABASE_URL = os.environ.get("DTE_DATABASE_URL")
if DTE_DATABASE_URL is None:
    pytest.skip("DTE_DATABASE_URL unset", allow_module_level=True)

SYNC_URL = DTE_DATABASE_URL.replace("+asyncpg", "")
TABLES = {"pipelines", "pipeline_revisions", "sources", "destinations",
          "lookup_tables", "eval_sets", "eval_examples", "dashboards"}


def _alembic(fn: str, rev: str, monkeypatch) -> None:
    from alembic.config import Config

    from alembic import command

    monkeypatch.setenv("DTE_DATABASE_URL", SYNC_URL)
    getattr(command, fn)(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), rev)


def _tenant_tables(conn) -> set[str]:
    return set(conn.execute(text(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'dte' AND column_name = 'tenant_id'"
    )).scalars())


def _dup_pipeline_name_rejected(conn) -> bool:
    conn.execute(text("INSERT INTO dte.pipelines (id, name, sources, steps, output_id) "
                      "VALUES ('m091a', 'm091', '[]', '[]', 'x')"))
    try:
        with conn.begin_nested():
            conn.execute(text("INSERT INTO dte.pipelines (id, name, sources, steps, output_id) "
                              "VALUES ('m091b', 'm091', '[]', '[]', 'x')"))
        return False
    except Exception:
        return True


def test_drop_and_restore_tenant_id(monkeypatch):
    engine = create_engine(SYNC_URL)
    _alembic("upgrade", "head", monkeypatch)
    with engine.connect() as conn:
        assert _tenant_tables(conn) == set()
        assert _dup_pipeline_name_rejected(conn)
        conn.rollback()

    _alembic("downgrade", "041", monkeypatch)
    try:
        with engine.connect() as conn:
            assert _tenant_tables(conn) == TABLES
            default = conn.execute(text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_schema = 'dte' AND table_name = 'pipelines' AND column_name = 'tenant_id'"
            )).scalar()
            assert default.startswith("'default'")
            assert _dup_pipeline_name_rejected(conn)
            conn.rollback()
            # Same name under two tenants: legal before, must survive the upgrade.
            for rid, tenant in (("m091x", "a"), ("m091y", "b")):
                conn.execute(text("INSERT INTO dte.pipelines (id, name, sources, steps, output_id, tenant_id) "
                                  "VALUES (:id, 'm091dup', '[]', '[]', 'x', :t)"), {"id": rid, "t": tenant})
            conn.commit()
    finally:
        _alembic("upgrade", "head", monkeypatch)
    with engine.begin() as conn:
        names = conn.execute(text("SELECT name FROM dte.pipelines WHERE id IN ('m091x', 'm091y')")).scalars().all()
        conn.execute(text("DELETE FROM dte.pipelines WHERE id IN ('m091x', 'm091y')"))
    assert len(names) == 2 and len(set(names)) == 2
