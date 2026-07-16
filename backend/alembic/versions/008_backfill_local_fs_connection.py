"""backfill connection_id for local_fs sources / destinations

Rows saved before plan-016 wired `connection_id` (or during the window
between plan-016 and the store-layer fix that missed the column) can be
safely repointed at a singleton `local_fs_default` connection when they
have no credential material to preserve: `filesystem` sources and
`json_file` / `csv_file` destinations.

Other source/dest types carry real credentials in `config` and need
Python-level extraction — those are left alone and must be handled by
`backend/scripts/migrate_extract_connections.py`.

Idempotent: only touches rows where `connection_id IS NULL`.

Revision ID: 008
Revises: 007
Create Date: 2026-07-16
"""
from alembic import op
from sqlalchemy import text


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


LOCAL_FS_DEFAULT_ID = "local_fs_default"


def upgrade() -> None:
    bind = op.get_bind()

    needs_source = bind.execute(text(
        "SELECT 1 FROM sources WHERE connection_id IS NULL AND source_type = 'filesystem' LIMIT 1"
    )).first()
    needs_dest = bind.execute(text(
        "SELECT 1 FROM destinations WHERE connection_id IS NULL "
        "AND (config->>'type') IN ('json_file', 'csv_file') LIMIT 1"
    )).first()
    if not needs_source and not needs_dest:
        return

    # Ensure singleton local_fs connection exists. `credentials_encrypted`
    # is opaque to this migration — we use the active resolver so both
    # env (plaintext JSON) and Fernet-configured deployments produce a
    # blob their own resolver can decrypt later.
    from dte.secrets import get_secret_resolver
    resolver = get_secret_resolver()
    empty_blob = resolver.encrypt({})

    bind.execute(
        text(
            "INSERT INTO connections (id, connection_type, credentials_encrypted) "
            "VALUES (:id, 'local_fs', :blob) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": LOCAL_FS_DEFAULT_ID, "blob": empty_blob},
    )

    bind.execute(text(
        "UPDATE sources SET connection_id = :id "
        "WHERE connection_id IS NULL AND source_type = 'filesystem'"
    ), {"id": LOCAL_FS_DEFAULT_ID})

    bind.execute(text(
        "UPDATE destinations SET connection_id = :id "
        "WHERE connection_id IS NULL AND (config->>'type') IN ('json_file', 'csv_file')"
    ), {"id": LOCAL_FS_DEFAULT_ID})


def downgrade() -> None:
    # Non-destructive: leave the backfilled connection_id refs in place.
    # The connections row can be removed manually if truly desired.
    pass
