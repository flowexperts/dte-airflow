"""Integration tests for PostgresScheduleStore (plan 047 task 2).

Requires a live Postgres with migration 032 applied; auto-skips when
DATABASE_URL is unset.

Covers:
- Normal tenant-scoped CRUD (get/save/list_for_pipeline/delete) respects
  RLS — a schedule created under tenant A is invisible to tenant B.
- `ON DELETE CASCADE`: deleting the owning pipeline removes the schedule.
- `list_due` deliberately bypasses RLS — it must see due schedules across
  every tenant in one call (the ticker has no per-request tenant context),
  while still reporting each row's real `tenant_id`.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="requires DATABASE_URL"),
]

from dte.models.pipeline import ScheduleBase
from dte.store.postgres import PostgresPipelineStore, PostgresScheduleStore
from dte.tenancy import set_current_tenant, tenant_context_var


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_pipeline(session_factory, pid: str, tenant_id: str) -> None:
    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        await s.execute(
            text("""
                INSERT INTO pipelines (id, name, sources, steps, output_id, tenant_id)
                VALUES (:id, :name, '[]'::jsonb, '[]'::jsonb, 'dest', :tenant_id)
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": pid, "name": pid, "tenant_id": tenant_id},
        )
        await s.commit()


async def test_schedule_crud_respects_tenant_rls(session_factory):
    tenant_a = f"sched-a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"sched-b-{uuid.uuid4().hex[:8]}"
    pid = f"sched-p-{uuid.uuid4().hex[:8]}"
    await _seed_pipeline(session_factory, pid, tenant_a)

    store = PostgresScheduleStore(session_factory)

    token = set_current_tenant(tenant_a)
    try:
        await store.save(ScheduleBase(
            id=f"sched-{uuid.uuid4().hex[:8]}", pipeline_id=pid,
            cron_expr="0 2 * * *", tenant_id=tenant_a,
        ))
        as_a = await store.list_for_pipeline(pid)
        assert len(as_a) == 1
    finally:
        tenant_context_var.reset(token)

    token = set_current_tenant(tenant_b)
    try:
        as_b = await store.list_for_pipeline(pid)
        assert as_b == []
    finally:
        tenant_context_var.reset(token)


async def test_schedule_cascade_deletes_with_pipeline(session_factory):
    tenant = f"sched-cascade-{uuid.uuid4().hex[:8]}"
    pid = f"sched-cascade-p-{uuid.uuid4().hex[:8]}"
    sid = f"sched-cascade-s-{uuid.uuid4().hex[:8]}"
    await _seed_pipeline(session_factory, pid, tenant)

    store = PostgresScheduleStore(session_factory)
    token = set_current_tenant(tenant)
    try:
        await store.save(ScheduleBase(
            id=sid, pipeline_id=pid, cron_expr="0 2 * * *", tenant_id=tenant,
        ))
        assert await store.get(sid) is not None
    finally:
        tenant_context_var.reset(token)

    p_store = PostgresPipelineStore(session_factory)
    token = set_current_tenant(tenant)
    try:
        await p_store.delete(pid)
    finally:
        tenant_context_var.reset(token)

    # Cascade fired at the DB layer — schedule is gone regardless of tenant
    # context (RLS-bypass read to make the assertion tenant-context-proof).
    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security = off"))
        result = await s.execute(text("SELECT id FROM schedules WHERE id = :id"), {"id": sid})
        assert result.mappings().fetchone() is None


async def test_list_due_sees_every_tenant_and_reports_real_tenant_id(session_factory):
    tenant_a = f"sched-due-a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"sched-due-b-{uuid.uuid4().hex[:8]}"
    pid_a = f"sched-due-pa-{uuid.uuid4().hex[:8]}"
    pid_b = f"sched-due-pb-{uuid.uuid4().hex[:8]}"
    await _seed_pipeline(session_factory, pid_a, tenant_a)
    await _seed_pipeline(session_factory, pid_b, tenant_b)

    now = datetime.now(UTC)
    store = PostgresScheduleStore(session_factory)
    sid_a = f"due-a-{uuid.uuid4().hex[:8]}"
    sid_b = f"due-b-{uuid.uuid4().hex[:8]}"

    token = set_current_tenant(tenant_a)
    try:
        await store.save(ScheduleBase(
            id=sid_a, pipeline_id=pid_a, cron_expr="0 2 * * *",
            tenant_id=tenant_a, next_run_at=now - timedelta(minutes=1),
        ))
    finally:
        tenant_context_var.reset(token)

    token = set_current_tenant(tenant_b)
    try:
        await store.save(ScheduleBase(
            id=sid_b, pipeline_id=pid_b, cron_expr="0 2 * * *",
            tenant_id=tenant_b, next_run_at=now - timedelta(minutes=1),
        ))
    finally:
        tenant_context_var.reset(token)

    # No tenant context set at all — mirrors the ticker's process-level call.
    due = await store.list_due(now)
    due_ids = {(s.id, s.tenant_id) for s in due}
    assert (sid_a, tenant_a) in due_ids
    assert (sid_b, tenant_b) in due_ids


async def test_advance_updates_regardless_of_tenant_context(session_factory):
    tenant = f"sched-adv-{uuid.uuid4().hex[:8]}"
    pid = f"sched-adv-p-{uuid.uuid4().hex[:8]}"
    sid = f"sched-adv-s-{uuid.uuid4().hex[:8]}"
    await _seed_pipeline(session_factory, pid, tenant)

    now = datetime.now(UTC)
    store = PostgresScheduleStore(session_factory)
    token = set_current_tenant(tenant)
    try:
        await store.save(ScheduleBase(
            id=sid, pipeline_id=pid, cron_expr="0 2 * * *",
            tenant_id=tenant, next_run_at=now,
        ))
    finally:
        tenant_context_var.reset(token)

    later = now + timedelta(hours=1)
    await store.advance(sid, next_run_at=later, last_run_id="run-xyz", last_fired_at=now)

    token = set_current_tenant(tenant)
    try:
        row = await store.get(sid)
    finally:
        tenant_context_var.reset(token)
    assert row.next_run_at == later
    assert row.last_run_id == "run-xyz"
