"""auto-set runs.finished_at when status becomes terminal

Revision ID: 003
Revises: 002
Create Date: 2026-07-12
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION runs_set_finished_at()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.status IN ('completed', 'failed') AND NEW.finished_at IS NULL THEN
                NEW.finished_at := NOW();
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS runs_set_finished_at_trigger ON runs;
        CREATE TRIGGER runs_set_finished_at_trigger
        BEFORE UPDATE ON runs
        FOR EACH ROW EXECUTE FUNCTION runs_set_finished_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS runs_set_finished_at_trigger ON runs")
    op.execute("DROP FUNCTION IF EXISTS runs_set_finished_at()")
