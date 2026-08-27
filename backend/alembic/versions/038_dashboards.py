"""Dashboards — layout for pipelines that draw instead of write (plan 064).

One table. A dashboard holds an ordered list of tiles in JSONB; each tile
names a pipeline and a chart spec. There is no dashboard run and no
dashboard execution path — a tile's rows come from the pipeline preview
endpoint, which already existed.

**`tile.pipeline_id` has no foreign key**, because tiles live inside JSONB
and Postgres cannot enforce a reference from there. A deleted pipeline
therefore leaves a dead tile, which the UI renders as "pipeline not found"
on that tile alone while its siblings keep drawing. That is deliberate: the
alternative (a 409 blocking pipeline deletion, as `lookup_tables` does) trades
a visible, recoverable tile error for an undeletable pipeline.

**UNIQUE (tenant_id, name)** matches every other named entity here — the
frontend routes by id but people identify a dashboard by its name, and two
called "Ops" make the list unusable.

Revision ID: 038
Revises: 037
"""
from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS dashboards (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            name        TEXT NOT NULL,
            description TEXT,
            tiles       JSONB NOT NULL DEFAULT '[]',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_dashboards_tenant_id ON dashboards (tenant_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_dashboards_tenant_name "
        "ON dashboards (tenant_id, name)"
    )

    # RLS — same pattern as migration 016's _RLS_TABLES loop and 032's table.
    # Not optional: `_open_tenant_session` sets `dte.tenant_id` on every read
    # regardless, so without a policy the table is silently cross-tenant
    # readable while every query still returns plausible rows.
    op.execute("ALTER TABLE dashboards ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dashboards FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON dashboards
        USING (tenant_id = current_setting('dte.tenant_id', true)::text)
    """)

    # Grant the new permissions to the roles migration 012 seeded. Adding a
    # value to `Permission` in the code only changes what *may* be checked —
    # the roles table holds what is actually granted, so without this an
    # existing admin gets a 403 on every dashboard route.
    op.execute(
        "UPDATE roles SET permissions = permissions || "
        "ARRAY['dashboard:read', 'dashboard:write', 'dashboard:delete']::text[] "
        "WHERE id = 'admin' AND NOT ('dashboard:read' = ANY(permissions))"
    )
    op.execute(
        "UPDATE roles SET permissions = permissions || "
        "ARRAY['dashboard:read', 'dashboard:write']::text[] "
        "WHERE id = 'editor' AND NOT ('dashboard:read' = ANY(permissions))"
    )
    op.execute(
        "UPDATE roles SET permissions = permissions || ARRAY['dashboard:read']::text[] "
        "WHERE id = 'viewer' AND NOT ('dashboard:read' = ANY(permissions))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE roles SET permissions = ARRAY("
        "  SELECT p FROM unnest(permissions) AS p WHERE p NOT LIKE 'dashboard:%'"
        ")::text[]"
    )
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dashboards")
    op.execute("DROP INDEX IF EXISTS uq_dashboards_tenant_name")
    op.execute("DROP INDEX IF EXISTS ix_dashboards_tenant_id")
    op.execute("DROP TABLE IF EXISTS dashboards")
