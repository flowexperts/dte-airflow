"""lookup_tables table

Revision ID: 010
Revises: 009
Create Date: 2026-07-17
"""
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS lookup_tables (
            id          TEXT PRIMARY KEY,
            name        TEXT,
            mappings    JSONB NOT NULL,
            "default"   TEXT,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lookup_tables")
