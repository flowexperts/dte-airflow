"""Add pipeline_type column to pipelines; make output_id nullable.

Quality pipelines (pipeline_type='quality') produce a quality report instead
of writing to a destination, so output_id is no longer required for all rows.

Revision ID: 026
Revises: 025
Create Date: 2026-08-04
"""
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE pipelines
            ADD COLUMN IF NOT EXISTS pipeline_type TEXT NOT NULL DEFAULT 'transform'
    """)
    op.execute("""
        ALTER TABLE pipelines
            ALTER COLUMN output_id DROP NOT NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE pipelines DROP COLUMN IF EXISTS pipeline_type")
    op.execute("""
        UPDATE pipelines SET output_id = '' WHERE output_id IS NULL
    """)
    op.execute("""
        ALTER TABLE pipelines ALTER COLUMN output_id SET NOT NULL
    """)
