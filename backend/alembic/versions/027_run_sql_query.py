"""Add sql_query JSONB column to runs table.

Stores the compiled SQL for each run: {step_sqls: {idx: sql}, final_sql: sql}.
Default is NULL so existing runs stay valid without a backfill.

Revision ID: 027
Revises: 026
Create Date: 2026-08-04
"""
from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE runs
            ADD COLUMN IF NOT EXISTS sql_query JSONB
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS sql_query")
