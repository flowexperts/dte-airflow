"""Typed pipeline inputs + persisted trigger-time context.

- `pipelines.params jsonb NOT NULL DEFAULT '[]'` — declared PipelineParam list.
- `runs.params jsonb NULL` — the resolved `{params, now, today, …}` context
  frozen at trigger time so each run's inputs are inspectable after the fact.

Revision ID: 019
Revises: 018
Create Date: 2026-07-31
"""
import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS params JSONB"
    ))
    conn.execute(sa.text(
        "ALTER TABLE pipelines "
        "ADD COLUMN IF NOT EXISTS params JSONB NOT NULL DEFAULT '[]'::jsonb"
    ))


def downgrade():
    op.drop_column("pipelines", "params")
    op.drop_column("runs", "params")
