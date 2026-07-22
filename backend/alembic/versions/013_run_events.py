"""Per-step run events.

Emits one row per (run, step) with phase transitions. The frontend Timeline
reads from `GET /api/runs/{id}/events`.

Revision ID: 013
Revises: 012
Create Date: 2026-07-22
"""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS run_events (
            id            TEXT PRIMARY KEY,
            run_id        TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            step_index    INTEGER NOT NULL,
            op            TEXT NOT NULL,
            status        TEXT NOT NULL CHECK (status IN ('started','completed','failed','skipped')),
            message       TEXT,
            started_at    TIMESTAMPTZ DEFAULT NOW(),
            finished_at   TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_run_events_run_id ON run_events(run_id, step_index)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS run_events")
