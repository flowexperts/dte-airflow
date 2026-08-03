"""Add quality_checks JSONB column to runs table.

Stores per-contract QualityResult list for each run. Default is an empty
array so existing runs remain valid without a backfill.

Revision ID: 025
Revises: 024
Create Date: 2026-08-04
"""
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE runs
            ADD COLUMN IF NOT EXISTS quality_checks JSONB NOT NULL DEFAULT '[]'::jsonb
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS quality_checks")
