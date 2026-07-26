"""Integration tests: RLS enforcement through PostgresPipelineStore.

Verifies that the store methods now route through _open_tenant_session,
which sets ``SET LOCAL dte.tenant_id`` so the RLS policies from
migration 016 are active on every store call.

Skips automatically when DATABASE_URL is not set (no live Postgres).

Threat model:
- ``list()`` with tenant A's contextvar sees only tenant A's rows.
- ``get(id_of_B)`` with tenant A's contextvar returns None.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dte.store.postgres import PostgresPipelineStore
from dte.tenancy import set_current_tenant, tenant_context_var

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Module-scoped fixtures (one engine / factory per test module run)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping RLS enforcement tests")
    return url


@pytest.fixture(scope="module")
def session_factory(db_url):
    engine = create_async_engine(db_url)
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_pipeline_raw(session_factory, pipeline_id: str, tenant_id: str) -> None:
    """Bypass RLS to insert a pipeline directly (setup only)."""
    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        await s.execute(
            text("""
                INSERT INTO pipelines (id, name, sources, steps, output_id, tenant_id)
                VALUES (:id, :name, '[]'::jsonb, '[]'::jsonb, 'dest', :tenant_id)
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": pipeline_id, "name": f"rls-test-{pipeline_id}", "tenant_id": tenant_id},
        )
        await s.commit()


async def _ensure_tenant(session_factory, tenant_id: str) -> None:
    async with session_factory() as s:
        await s.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"),
            {"id": tenant_id, "name": tenant_id},
        )
        await s.commit()


async def _delete_pipeline_raw(session_factory, pipeline_id: str) -> None:
    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        await s.execute(text("DELETE FROM pipelines WHERE id = :id"), {"id": pipeline_id})
        await s.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_list_filters_by_tenant(session_factory):
    """PostgresPipelineStore.list() returns only the calling tenant's rows.

    Two pipelines seeded via raw SQL with different tenant_ids; the store
    called with tenant-a's contextvar should only see tenant-a's pipeline.
    """
    tenant_a = f"rls-enf-a-{uuid.uuid4().hex[:6]}"
    tenant_b = f"rls-enf-b-{uuid.uuid4().hex[:6]}"
    pipe_a = f"rls-enf-pipe-a-{uuid.uuid4().hex[:6]}"
    pipe_b = f"rls-enf-pipe-b-{uuid.uuid4().hex[:6]}"

    await _ensure_tenant(session_factory, tenant_a)
    await _ensure_tenant(session_factory, tenant_b)
    await _insert_pipeline_raw(session_factory, pipe_a, tenant_a)
    await _insert_pipeline_raw(session_factory, pipe_b, tenant_b)

    try:
        store = PostgresPipelineStore(session_factory)

        # Set contextvar to tenant-a and call list().
        token = set_current_tenant(tenant_a)
        try:
            pipelines = await store.list(limit=200)
        finally:
            tenant_context_var.reset(token)

        ids = [p.id for p in pipelines]
        assert pipe_a in ids, "tenant-a's pipeline must appear in tenant-a's list"
        assert pipe_b not in ids, "tenant-b's pipeline must NOT appear in tenant-a's list"

    finally:
        await _delete_pipeline_raw(session_factory, pipe_a)
        await _delete_pipeline_raw(session_factory, pipe_b)


@pytest.mark.asyncio
async def test_store_get_cross_tenant_returns_none(session_factory):
    """PostgresPipelineStore.get() returns None for a row owned by another tenant.

    Seeded via raw SQL as tenant-b; queried via store as tenant-a.
    """
    tenant_a = f"rls-enf-a-{uuid.uuid4().hex[:6]}"
    tenant_b = f"rls-enf-b-{uuid.uuid4().hex[:6]}"
    pipe_b = f"rls-enf-get-{uuid.uuid4().hex[:6]}"

    await _ensure_tenant(session_factory, tenant_a)
    await _ensure_tenant(session_factory, tenant_b)
    await _insert_pipeline_raw(session_factory, pipe_b, tenant_b)

    try:
        store = PostgresPipelineStore(session_factory)

        token = set_current_tenant(tenant_a)
        try:
            result = await store.get(pipe_b)
        finally:
            tenant_context_var.reset(token)

        assert result is None, (
            f"tenant-a queried pipeline {pipe_b} owned by tenant-b; "
            "RLS should return None but got a row"
        )

    finally:
        await _delete_pipeline_raw(session_factory, pipe_b)


@pytest.mark.asyncio
async def test_store_get_own_tenant_succeeds(session_factory):
    """PostgresPipelineStore.get() returns its own row when the contextvar matches."""
    tenant_a = f"rls-enf-a-{uuid.uuid4().hex[:6]}"
    pipe_a = f"rls-enf-own-{uuid.uuid4().hex[:6]}"

    await _ensure_tenant(session_factory, tenant_a)
    await _insert_pipeline_raw(session_factory, pipe_a, tenant_a)

    try:
        store = PostgresPipelineStore(session_factory)

        token = set_current_tenant(tenant_a)
        try:
            result = await store.get(pipe_a)
        finally:
            tenant_context_var.reset(token)

        assert result is not None, "tenant should see its own pipeline"
        assert result.id == pipe_a

    finally:
        await _delete_pipeline_raw(session_factory, pipe_a)
