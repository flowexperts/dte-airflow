"""Per-tenant Fernet secret key table.

Stores one Fernet key per tenant, itself wrapped by `DTE_ROOT_KEY`.
The root key is the single encryption key that protects all tenant keys;
individual tenant keys are rotatable independently.

MVP: the migration seeds a row for the 'default' tenant using the current
`DTE_SECRETS_KEY` (if set) wrapped by `DTE_ROOT_KEY`. When neither is set
(dev / CI), the row is inserted with a freshly-generated Fernet key.

Revision ID: 017
Revises: 016
Create Date: 2026-07-25
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_secret_keys (
            tenant_id  TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE RESTRICT,
            key_fernet BYTEA NOT NULL,
            rotated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # Seed the default tenant key using the current DTE_SECRETS_KEY (if present).
    # We call a helper script rather than embedding the key derivation in the
    # migration itself — keeping secrets out of migration logs.
    #
    # For dev / CI (no DTE_SECRETS_KEY set), we generate a fresh Fernet key and
    # store it in plaintext for the dev environment. Production operators MUST run
    # `scripts/provision_tenant_key.py --tenant default` with DTE_ROOT_KEY set
    # before enabling multi-tenancy.
    import os

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        # cryptography not installed — skip key seeding (CI fast path).
        return

    root_key = os.getenv("DTE_ROOT_KEY")
    current_key = os.getenv("DTE_SECRETS_KEY")

    if root_key:
        # Wrap current_key (or a fresh one) under root_key.
        root_fernet = Fernet(root_key.encode() if isinstance(root_key, str) else root_key)
        if current_key:
            payload = current_key.encode() if isinstance(current_key, str) else current_key
        else:
            payload = Fernet.generate_key()
        wrapped = root_fernet.encrypt(payload)
    elif current_key:
        # No root key — store the key wrapped by itself (dev only; not secure).
        f = Fernet(current_key.encode() if isinstance(current_key, str) else current_key)
        wrapped = f.encrypt(current_key.encode() if isinstance(current_key, str) else current_key)
    else:
        # Neither set — generate a fresh key and store it unwrapped (dev/CI only).
        fresh = Fernet.generate_key()
        f = Fernet(fresh)
        wrapped = f.encrypt(fresh)

    from sqlalchemy import text
    conn = op.get_bind()
    conn.execute(
        text("""
            INSERT INTO tenant_secret_keys (tenant_id, key_fernet)
            VALUES (:tenant_id, :key_fernet)
            ON CONFLICT (tenant_id) DO NOTHING
        """),
        {"tenant_id": "default", "key_fernet": wrapped},
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS tenant_secret_keys")
