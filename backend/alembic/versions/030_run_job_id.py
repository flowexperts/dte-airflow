"""Add job_id to runs (plan 046 task 5).

Maps a run row to the procrastinate job that executes it, so
`POST /runs/{id}/cancel` can translate a run id into a job id
(queue-native cancel, task 9) instead of the process-local `run_registry`
this plan removes. NULL for every run created while `DTE_JOB_QUEUE_ENABLED`
is off — those still run via the in-process `asyncio.create_task` path and
have no job.

`runs` is not expected to be a > 100k-row backfill target for this column
(it stays NULL for pre-existing rows), so a plain `ADD COLUMN` is
appropriate — no `batched_update` needed.

Revision ID: 030
Revises: 029
Create Date: 2026-08-07
"""
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS job_id BIGINT")


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS job_id")
