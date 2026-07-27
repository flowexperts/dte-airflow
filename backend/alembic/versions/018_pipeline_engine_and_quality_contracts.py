"""Add engine and quality_contracts columns to pipelines table.

Both columns are declared on the Pipeline SQLModel (table=True) class but were
never added via a migration, making fresh Postgres installs fail at pipeline
create time.

- engine: TEXT NOT NULL DEFAULT 'duckdb'
- quality_contracts: JSONB NOT NULL DEFAULT '[]'

Revision ID: 018
Revises: 017
Create Date: 2026-07-25
"""
import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    # Use IF NOT EXISTS so the migration is idempotent for databases that
    # already had these columns hand-applied (e.g. by the load-test agent's
    # workaround ALTER TABLE statements).
    conn = op.get_bind()
    conn.execute(sa.text(
        "ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS engine TEXT NOT NULL DEFAULT 'duckdb'"
    ))
    conn.execute(sa.text(
        "ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS quality_contracts JSONB NOT NULL DEFAULT '[]'"
    ))


def downgrade():
    op.drop_column("pipelines", "quality_contracts")
    op.drop_column("pipelines", "engine")
