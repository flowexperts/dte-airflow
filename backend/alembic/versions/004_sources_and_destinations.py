"""sources and destinations tables

Revision ID: 004
Revises: 003
Create Date: 2026-07-14
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id           TEXT PRIMARY KEY,
            source_type  TEXT NOT NULL,
            config       JSONB NOT NULL,
            table_name   TEXT NOT NULL,
            created_at   TIMESTAMPTZ DEFAULT now(),
            updated_at   TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS destinations (
            id          TEXT PRIMARY KEY,
            dest_type   TEXT NOT NULL,
            config      JSONB NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS destinations")
    op.execute("DROP TABLE IF EXISTS sources")
