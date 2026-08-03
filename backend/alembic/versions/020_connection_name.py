"""Editable, unique-per-tenant `name` for connections + UUID default for new ids.

Historic string ids (including `local_fs`) are preserved verbatim so every
existing source/destination.connection_id reference keeps resolving.

New connections created after this migration get a server-generated UUID for
`id` (the model's default_factory), while users edit `name` freely.

Revision ID: 020
Revises: 019
Create Date: 2026-08-03
"""
import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE connections ADD COLUMN IF NOT EXISTS name TEXT"))
    # Backfill: name := id for every existing row. Small table (<10k rows in
    # any realistic install), plain UPDATE is fine.
    conn.execute(sa.text("UPDATE connections SET name = id WHERE name IS NULL"))
    conn.execute(sa.text("ALTER TABLE connections ALTER COLUMN name SET NOT NULL"))
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_connections_tenant_name "
        "ON connections (tenant_id, name)"
    ))


def downgrade():
    op.execute("DROP INDEX IF EXISTS ux_connections_tenant_name")
    op.drop_column("connections", "name")
