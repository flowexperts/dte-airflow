"""Enable Postgres Row-Level Security (RLS) on all tenant-scoped tables.

Each table gets:
  - ROW LEVEL SECURITY ENABLED
  - FORCE ROW LEVEL SECURITY (applies even to the table owner)
  - A USING policy that checks tenant_id = current_setting('dte.tenant_id')

The `dte.tenant_id` session variable is set per-request by
`dte.api.middleware.TenantContextMiddleware` (see plan 030).

Admin / ops queries that need cross-tenant access run:
    SET LOCAL row_security = off;
in the session — this is grep-detectable and reviewed.

Revision ID: 016
Revises: 015
Create Date: 2026-07-25
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

# Tables to protect. `tenants` itself is excluded — it's the authority table
# and must be readable by the app to resolve tenant ids.
# `roles` and `user_roles` are also tenant-agnostic RBAC tables.
_RLS_TABLES = [
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
    for table in _RLS_TABLES:
        # Enable RLS.
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # Force RLS so even the table owner can't bypass it.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # Permissive policy — row is visible iff tenant_id matches session var.
        # current_setting(..., true) with missing_ok=true returns '' when the
        # var is unset, which matches no row — a safe default.
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('dte.tenant_id', true)::text)
        """)


def downgrade():
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
