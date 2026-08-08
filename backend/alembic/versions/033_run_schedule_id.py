"""Add schedule_id to runs (plan 047 task 4).

Lets the UI distinguish "ran because a human clicked" from "ran because
it was 2am". `ON DELETE SET NULL` (not CASCADE): deleting a schedule
should not delete its run history, only drop the link — the run stays a
legitimate audit record of a real execution.

Revision ID: 033
Revises: 032
Create Date: 2026-08-08
"""
from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS schedule_id "
        "TEXT REFERENCES schedules(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_runs_schedule_id ON runs (schedule_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_runs_schedule_id")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS schedule_id")
