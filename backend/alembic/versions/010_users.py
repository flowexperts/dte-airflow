"""Create users table with updated_at trigger.

Revision ID: 010
Revises: 009
Create Date: 2026-07-17
"""
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            text PRIMARY KEY,
            email         text NOT NULL UNIQUE,
            password_hash text NOT NULL,
            is_active     boolean NOT NULL DEFAULT true,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS users_email_idx ON users(email)")

    # BEFORE UPDATE trigger to keep updated_at current.
    op.execute("""
        CREATE OR REPLACE FUNCTION users_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS users_set_updated_at_trigger ON users;
        CREATE TRIGGER users_set_updated_at_trigger
        BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION users_set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS users_set_updated_at_trigger ON users")
    op.execute("DROP FUNCTION IF EXISTS users_set_updated_at()")
    op.execute("DROP TABLE IF EXISTS users")
