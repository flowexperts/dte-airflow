"""connections table

Revision ID: 005
Revises: 004
Create Date: 2026-07-14
"""
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            id                      TEXT PRIMARY KEY,
            connection_type         TEXT NOT NULL,
            credentials_encrypted   BYTEA NOT NULL,
            created_at              TIMESTAMPTZ DEFAULT now(),
            updated_at              TIMESTAMPTZ DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS connections")
