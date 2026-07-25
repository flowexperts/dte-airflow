"""Pipeline revisions + run.revision_id.

Every accepted POST/PUT on a pipeline persists an immutable revision row.
Runs pin to the revision id used to trigger them so support can answer
"which config produced this output?".

Revision ID: 014
Revises: 013
Create Date: 2026-07-25
"""
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_revisions (
            id           TEXT PRIMARY KEY,
            pipeline_id  TEXT NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
            config       JSONB NOT NULL,
            changed_by   TEXT,
            changed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            summary      TEXT
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pipeline_revisions_pipeline_changed "
        "ON pipeline_revisions (pipeline_id, changed_at DESC)"
    )
    op.execute(
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS revision_id TEXT "
        "REFERENCES pipeline_revisions(id) ON DELETE SET NULL"
    )


def downgrade():
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS revision_id")
    op.execute("DROP INDEX IF EXISTS ix_pipeline_revisions_pipeline_changed")
    op.execute("DROP TABLE IF EXISTS pipeline_revisions")
