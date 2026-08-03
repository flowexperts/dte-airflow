"""Editable, unique-per-tenant `name` for destinations + UUID default for new ids.

Historic string ids are preserved verbatim so every `pipelines.output_id`
reference keeps resolving without a rewrite.

Revision ID: 022
Revises: 021
Create Date: 2026-08-03
"""
import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE destinations ADD COLUMN IF NOT EXISTS name TEXT"))
    conn.execute(sa.text("UPDATE destinations SET name = id WHERE name IS NULL"))
    conn.execute(sa.text("ALTER TABLE destinations ALTER COLUMN name SET NOT NULL"))
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_destinations_tenant_name "
        "ON destinations (tenant_id, name)"
    ))


def downgrade():
    op.execute("DROP INDEX IF EXISTS ux_destinations_tenant_name")
    op.drop_column("destinations", "name")
