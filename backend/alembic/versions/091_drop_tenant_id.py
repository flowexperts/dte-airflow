"""Drop `tenant_id` (plan 091).

Migration 039 dropped the `tenants` table and every RLS policy; the column
stayed behind, always 'default'. Dropping it takes its indexes with it,
including the UNIQUE(tenant_id, name) ones, so names get a plain UNIQUE(name).
Rows that only differed by tenant are disambiguated first, as 024 did.

Revision ID: 091
Revises: 041
"""
from alembic import op

revision = "091"
down_revision = "041"
branch_labels = None
depends_on = None

TABLES = ("pipelines", "pipeline_revisions", "sources", "destinations",
          "lookup_tables", "eval_sets", "eval_examples", "dashboards")
# table -> name of its old UNIQUE(tenant_id, name) index
NAMED = {"pipelines": "ux_pipelines_tenant_name", "sources": "ux_sources_tenant_name",
         "destinations": "ux_destinations_tenant_name",
         "lookup_tables": "ux_lookup_tables_tenant_name",
         "dashboards": "uq_dashboards_tenant_name"}


def upgrade() -> None:
    for table in NAMED:
        op.execute(f"""
            WITH ranked AS (
              SELECT id, ROW_NUMBER() OVER (PARTITION BY name ORDER BY created_at, id) AS rn
              FROM {table}
            )
            UPDATE {table} t SET name = t.name || ' (' || SUBSTR(t.id, 1, 8) || ')'
            FROM ranked r WHERE t.id = r.id AND r.rn > 1
        """)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id")
    for table in NAMED:
        op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_name ON {table} (name)")


def downgrade() -> None:
    for table in NAMED:
        op.execute(f"DROP INDEX IF EXISTS ux_{table}_name")
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
    for table, index in NAMED.items():
        op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {index} ON {table} (tenant_id, name)")
