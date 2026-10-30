"""Pipeline notifications (plan 070).

`pipelines.notifications` JSONB: a list of `{notifier, params, on}`, part of
the spec and so of every revision. Separate from the schedule because manual
runs notify too.

Revision ID: 041
Revises: 040
"""
from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS notifications JSONB NOT NULL DEFAULT '[]'")


def downgrade() -> None:
    op.execute("ALTER TABLE pipelines DROP COLUMN IF EXISTS notifications")
