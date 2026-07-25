"""Add tenants table and tenant_id column to every user-owned table.

Backfills all existing rows to the 'default' tenant using
`batched_update` (per CLAUDE.md mandate for large backfills).

Revision ID: 015
Revises: 014
Create Date: 2026-07-25
"""
from alembic import op
from dte.alembic_util import batched_update

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


# Tables that need tenant_id. Order matters for FK deps.
_TENANT_SCOPED_TABLES = [
    "connections",
    "sources",
    "destinations",
    "lookup_tables",
    "pipelines",
    "runs",
    "run_events",
    "pipeline_revisions",
    "users",
]


def upgrade():
    # 1. Tenants table — the anchor for all tenant rows.
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # 2. Seed the default tenant (idempotent via ON CONFLICT).
    op.execute("""
        INSERT INTO tenants (id, name)
        VALUES ('default', 'Default Tenant')
        ON CONFLICT (id) DO NOTHING
    """)

    # 3. Add tenant_id column (nullable first so existing rows don't break),
    #    then backfill, then add the NOT NULL constraint.
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"""
            ALTER TABLE {table}
            ADD COLUMN IF NOT EXISTS tenant_id TEXT
        """)

        # Backfill via batched_update (safe for > 100k rows per CLAUDE.md).
        batched_update(
            op,
            table=table,
            set_clause="tenant_id = 'default'",
            where_clause="tenant_id IS NULL",
            batch_size=5000,
        )

        # Now that all rows have a value, enforce NOT NULL + default.
        op.execute(f"""
            ALTER TABLE {table}
            ALTER COLUMN tenant_id SET NOT NULL,
            ALTER COLUMN tenant_id SET DEFAULT 'default'
        """)

    # 4. Create indexes to make per-tenant list queries fast.
    for table in _TENANT_SCOPED_TABLES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id "
            f"ON {table} (tenant_id)"
        )


def downgrade():
    for table in reversed(_TENANT_SCOPED_TABLES):
        op.execute(
            f"DROP INDEX IF EXISTS ix_{table}_tenant_id"
        )
        op.execute(
            f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id"
        )

    op.execute("DROP TABLE IF EXISTS tenants")
