"""Editable, unique-per-tenant `name` for sources + UUID default for new ids.

Historic string ids are preserved verbatim so every
`pipelines.sources[]` reference keeps resolving without a JSONB rewrite.

Revision ID: 021
Revises: 020
Create Date: 2026-08-03
"""
import sqlalchemy as sa
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE sources ADD COLUMN IF NOT EXISTS name TEXT"))
    conn.execute(sa.text("UPDATE sources SET name = id WHERE name IS NULL"))
    conn.execute(sa.text("ALTER TABLE sources ALTER COLUMN name SET NOT NULL"))
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_sources_tenant_name "
        "ON sources (tenant_id, name)"
    ))


def downgrade():
    op.execute("DROP INDEX IF EXISTS ux_sources_tenant_name")
    op.drop_column("sources", "name")
