"""Add last_heartbeat_at to runs (plan 046 task 8).

Touched every HEARTBEAT_INTERVAL_SECONDS by the worker
(`dte.worker.tasks._heartbeat_loop`) while a distributed run is in
flight. `dte.worker.reaper` fails out any `running` run whose heartbeat
has gone stale by more than 2x that interval — the failure mode
`docs/runbooks/oncall/pipeline-stuck-running.md` documents, more likely
under k8s eviction with execution split across a worker pool. NULL for
runs executed via the in-process asyncio.create_task path (flag off) —
those aren't subject to the reaper.

Revision ID: 031
Revises: 030
Create Date: 2026-08-07
"""
from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS last_heartbeat_at")
