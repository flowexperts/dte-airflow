"""Create schedules table (plan 047 task 2).

Recurring triggers for one pipeline. `ON DELETE CASCADE` on `pipeline_id`:
deleting a pipeline must not leave a schedule firing into a 404 every
night. `ix_schedules_due` is a partial index on `next_run_at` scoped to
`enabled` rows — the ticker's `list_due` query (`enabled AND next_run_at
<= now`) is the only read path that matters at scale.

`tenant_id` follows the same NOT NULL DEFAULT 'default' + RLS policy
pattern as every other tenant-scoped table (migrations 015/016) so a
freshly created row is visible under the request's tenant immediately,
and single-tenant deployments (multi_tenant disabled) keep working
unchanged.

Revision ID: 032
Revises: 031
Create Date: 2026-08-08
"""
from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id            TEXT PRIMARY KEY,
            tenant_id     TEXT NOT NULL DEFAULT 'default',
            pipeline_id   TEXT NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
            cron_expr     TEXT NOT NULL,
            timezone      TEXT NOT NULL DEFAULT 'UTC',
            params        JSONB NOT NULL DEFAULT '{}',
            enabled       BOOLEAN NOT NULL DEFAULT true,
            overlap       TEXT NOT NULL DEFAULT 'skip',
            next_run_at   TIMESTAMPTZ,
            last_run_id   TEXT,
            last_fired_at TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_schedules_due ON schedules (next_run_at) "
        "WHERE enabled"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_schedules_pipeline_id ON schedules (pipeline_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_schedules_tenant_id ON schedules (tenant_id)")

    # RLS — same pattern as migration 016's _RLS_TABLES loop.
    op.execute("ALTER TABLE schedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE schedules FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON schedules
        USING (tenant_id = current_setting('dte.tenant_id', true)::text)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON schedules")
    op.execute("ALTER TABLE schedules DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE schedules NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS schedules")
