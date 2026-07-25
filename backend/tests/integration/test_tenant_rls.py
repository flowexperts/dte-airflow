"""Integration tests for Postgres Row-Level Security tenant isolation.

These tests require a live Postgres instance with migration 016 applied
(RLS policies). They auto-skip when DATABASE_URL is not set.

Threat model covered:
1. Cross-tenant read via list — tenant-a cannot see tenant-b's pipelines.
2. Cross-tenant read via direct id — tenant-a cannot fetch tenant-b's pipeline by id.
3. Cross-tenant write via referential spoofing — a pipeline save with a
   source owned by another tenant cannot succeed (the source lookup returns None).
"""
from __future__ import annotations

import os
import uuid
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import text

# Auto-skip when DATABASE_URL is not set
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping RLS integration tests")
    return url


@pytest.fixture(scope="module")
def session_factory(db_url):
    engine = create_async_engine(db_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _set_tenant(session, tenant_id: str):
    """Set the per-session RLS variable."""
    await session.execute(text("SET LOCAL dte.tenant_id = :t"), {"t": tenant_id})


async def _insert_pipeline(session, pipeline_id: str, tenant_id: str):
    await session.execute(
        text("""
            INSERT INTO pipelines (id, name, sources, steps, output_id, tenant_id)
            VALUES (:id, :name, '[]'::jsonb, '[]'::jsonb, 'dest', :tenant_id)
            ON CONFLICT (id) DO NOTHING
        """),
        {"id": pipeline_id, "name": f"Pipeline {pipeline_id}", "tenant_id": tenant_id},
    )
    await session.commit()


async def _insert_source(session, source_id: str, tenant_id: str):
    await session.execute(
        text("""
            INSERT INTO sources (id, connection_id, source_type, config, table_name, tenant_id)
            VALUES (:id, 'local_fs', 'filesystem', '{}'::jsonb, 'tbl', :tenant_id)
            ON CONFLICT (id) DO NOTHING
        """),
        {"id": source_id, "tenant_id": tenant_id},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_rls_list_pipelines_cross_tenant(session_factory):
    """Tenant-a cannot see tenant-b's pipelines via SELECT *."""
    pipe_a = f"rls-pipe-a-{uuid.uuid4().hex[:8]}"
    pipe_b = f"rls-pipe-b-{uuid.uuid4().hex[:8]}"
    tenant_a = "rls-tenant-a"
    tenant_b = "rls-tenant-b"

    # Setup: seed tenants + pipelines as superuser (bypass RLS for setup).
    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        await s.execute(
            text("INSERT INTO tenants (id, name) VALUES (:a, 'A'), (:b, 'B') ON CONFLICT DO NOTHING"),
            {"a": tenant_a, "b": tenant_b},
        )
        await s.commit()
        await _insert_pipeline(s, pipe_a, tenant_a)
        await _insert_pipeline(s, pipe_b, tenant_b)

    # Test: as tenant-a, SELECT should only return tenant-a's pipeline.
    async with session_factory() as s:
        await _set_tenant(s, tenant_a)
        result = await s.execute(
            text("SELECT id FROM pipelines WHERE id IN (:a, :b)"),
            {"a": pipe_a, "b": pipe_b},
        )
        ids = [r[0] for r in result.fetchall()]

    assert pipe_a in ids, "tenant-a should see its own pipeline"
    assert pipe_b not in ids, "tenant-a must NOT see tenant-b's pipeline"

    # Cleanup.
    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        await s.execute(
            text("DELETE FROM pipelines WHERE id IN (:a, :b)"), {"a": pipe_a, "b": pipe_b}
        )
        await s.commit()


@pytest.mark.asyncio
async def test_rls_get_pipeline_by_id_cross_tenant(session_factory):
    """Tenant-a cannot fetch tenant-b's pipeline by id."""
    pipe_b = f"rls-idtest-{uuid.uuid4().hex[:8]}"
    tenant_a = "rls-tenant-a"
    tenant_b = "rls-tenant-b"

    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        await s.execute(
            text("INSERT INTO tenants (id, name) VALUES (:a, 'A'), (:b, 'B') ON CONFLICT DO NOTHING"),
            {"a": tenant_a, "b": tenant_b},
        )
        await s.commit()
        await _insert_pipeline(s, pipe_b, tenant_b)

    # Query as tenant-a — should get 0 rows.
    async with session_factory() as s:
        await _set_tenant(s, tenant_a)
        result = await s.execute(
            text("SELECT id FROM pipelines WHERE id = :id"),
            {"id": pipe_b},
        )
        row = result.fetchone()

    assert row is None, "tenant-a must NOT see tenant-b's pipeline via direct id lookup"

    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        await s.execute(text("DELETE FROM pipelines WHERE id = :id"), {"id": pipe_b})
        await s.commit()


@pytest.mark.asyncio
async def test_rls_cross_tenant_source_not_visible(session_factory):
    """A source owned by tenant-b is invisible to tenant-a (simulates spoofing prevention)."""
    src_b = f"rls-src-{uuid.uuid4().hex[:8]}"
    tenant_a = "rls-tenant-a"
    tenant_b = "rls-tenant-b"

    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        await s.execute(
            text("INSERT INTO tenants (id, name) VALUES (:a, 'A'), (:b, 'B') ON CONFLICT DO NOTHING"),
            {"a": tenant_a, "b": tenant_b},
        )
        await s.commit()
        await _insert_source(s, src_b, tenant_b)

    # tenant-a tries to look up tenant-b's source by id — should get None.
    async with session_factory() as s:
        await _set_tenant(s, tenant_a)
        result = await s.execute(
            text("SELECT id FROM sources WHERE id = :id"),
            {"id": src_b},
        )
        row = result.fetchone()

    assert row is None, "tenant-a must NOT see tenant-b's source"

    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        await s.execute(text("DELETE FROM sources WHERE id = :id"), {"id": src_b})
        await s.commit()
