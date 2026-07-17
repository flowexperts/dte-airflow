"""RBAC — roles + user_roles.

Seeds three canned roles (admin/editor/viewer) and backfills any
existing user (i.e. the pre-023 `admin@admin.com` account) with the
`admin` role — otherwise the plan-022 bootstrap user gets locked out
of every route the moment this migration lands.

Revision ID: 012
Revises: 011
Create Date: 2026-07-17
"""
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


# Kept in sync with dte/security/permissions.py — see ALL_PERMISSIONS,
# EDITOR_PERMISSIONS, VIEWER_PERMISSIONS there. Duplicated here as
# literal strings because migrations shouldn't import runtime code.

_ALL = [
    "pipeline:read", "pipeline:write", "pipeline:delete", "pipeline:trigger",
    "source:read", "source:write", "source:delete",
    "destination:read", "destination:write", "destination:delete",
    "connection:read", "connection:write", "connection:delete", "connection:test",
    "lookup_table:read", "lookup_table:write", "lookup_table:delete",
    "run:read", "run:delete",
    "user:read", "user:write", "user:delete",
]

_EDITOR = [
    p for p in _ALL
    if p.endswith(":read") or p.endswith(":write") or p in ("pipeline:trigger", "connection:test")
]

_VIEWER = [p for p in _ALL if p.endswith(":read")]


def _sql_array(perms: list[str]) -> str:
    inner = ", ".join(f"'{p}'" for p in perms)
    return f"ARRAY[{inner}]::text[]"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id          text PRIMARY KEY,
            name        text NOT NULL UNIQUE,
            permissions text[] NOT NULL DEFAULT '{}',
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    # updated_at trigger — mirrors the users pattern.
    op.execute("""
        CREATE OR REPLACE FUNCTION roles_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS roles_set_updated_at_trigger ON roles;
        CREATE TRIGGER roles_set_updated_at_trigger
        BEFORE UPDATE ON roles
        FOR EACH ROW EXECUTE FUNCTION roles_set_updated_at();
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role_id text NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, role_id)
        )
    """)

    op.execute(
        f"INSERT INTO roles (id, name, permissions) VALUES "
        f"('admin',  'admin',  {_sql_array(_ALL)}), "
        f"('editor', 'editor', {_sql_array(_EDITOR)}), "
        f"('viewer', 'viewer', {_sql_array(_VIEWER)}) "
        f"ON CONFLICT (id) DO NOTHING"
    )

    # Backfill: any user already in the DB (only possible via plan-022's
    # DTE_ALLOW_REGISTRATION bootstrap) is promoted to admin so they
    # aren't locked out by the new guards in task 2.
    op.execute("""
        INSERT INTO user_roles (user_id, role_id)
        SELECT id, 'admin' FROM users
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_roles")
    op.execute("DROP TRIGGER IF EXISTS roles_set_updated_at_trigger ON roles")
    op.execute("DROP FUNCTION IF EXISTS roles_set_updated_at()")
    op.execute("DROP TABLE IF EXISTS roles")
