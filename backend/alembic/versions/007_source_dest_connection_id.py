"""add connection_id to sources and destinations

Revision ID: 007
Revises: 006
Create Date: 2026-07-16
"""
from alembic import op


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sources      ADD COLUMN IF NOT EXISTS connection_id TEXT")
    op.execute("ALTER TABLE destinations ADD COLUMN IF NOT EXISTS connection_id TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE sources      DROP COLUMN IF EXISTS connection_id")
    op.execute("ALTER TABLE destinations DROP COLUMN IF EXISTS connection_id")
