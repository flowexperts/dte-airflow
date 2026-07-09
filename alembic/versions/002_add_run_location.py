"""add location column to runs

Revision ID: 002
Revises: 001
Create Date: 2026-07-08
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS location TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS location")
