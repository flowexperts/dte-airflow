"""Enforce `name` NOT NULL + UNIQUE(tenant_id, name) on lookup_tables.

Historic string ids are preserved verbatim so every `steps[*].lookup_id`
reference inside pipelines.steps keeps resolving without a JSONB rewrite.

Revision ID: 023
Revises: 022
Create Date: 2026-08-03
"""
import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # `name` column already exists on lookup_tables (added in migration 011)
    # but was nullable. Backfill from id where NULL, then enforce.
    conn.execute(sa.text("UPDATE lookup_tables SET name = id WHERE name IS NULL"))
    conn.execute(sa.text("ALTER TABLE lookup_tables ALTER COLUMN name SET NOT NULL"))
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_lookup_tables_tenant_name "
        "ON lookup_tables (tenant_id, name)"
    ))


def downgrade():
    op.execute("DROP INDEX IF EXISTS ux_lookup_tables_tenant_name")
    op.execute("ALTER TABLE lookup_tables ALTER COLUMN name DROP NOT NULL")
