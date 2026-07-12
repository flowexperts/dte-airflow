"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-07-04
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS pipelines (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            definition  JSONB NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id            TEXT PRIMARY KEY,
            pipeline_id   TEXT NOT NULL REFERENCES pipelines(id),
            status        TEXT NOT NULL DEFAULT 'pending',
            error         TEXT,
            rows_written  INTEGER,
            started_at    TIMESTAMPTZ DEFAULT now(),
            finished_at   TIMESTAMPTZ
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS runs")
    op.execute("DROP TABLE IF EXISTS pipelines")
