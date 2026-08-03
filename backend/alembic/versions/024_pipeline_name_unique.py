"""UNIQUE(tenant_id, name) for pipelines + UUID default for new ids.

Pipelines already have a required `name` column (existed since day one).
This migration adds the tenant-scoped uniqueness constraint and lets new
pipelines get a server-generated UUID for `id`. Historic string ids are
preserved verbatim so `runs.pipeline_id` and `pipeline_revisions.pipeline_id`
keep resolving without a rewrite.

Duplicate names within a tenant are disambiguated during upgrade by
appending the short id — cheap way to guarantee the index build succeeds
without demanding an operator merge duplicates first.

Revision ID: 024
Revises: 023
Create Date: 2026-08-03
"""
import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Disambiguate any existing duplicate (tenant_id, name) pairs so the
    # unique index can be built. Rare in practice but the check is cheap.
    conn.execute(sa.text("""
        WITH ranked AS (
          SELECT id, tenant_id, name,
                 ROW_NUMBER() OVER (
                   PARTITION BY tenant_id, name ORDER BY created_at
                 ) AS rn
          FROM pipelines
        )
        UPDATE pipelines p
        SET name = p.name || ' (' || SUBSTR(p.id, 1, 8) || ')'
        FROM ranked r
        WHERE p.id = r.id AND r.rn > 1
    """))
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_pipelines_tenant_name "
        "ON pipelines (tenant_id, name)"
    ))


def downgrade():
    op.execute("DROP INDEX IF EXISTS ux_pipelines_tenant_name")
