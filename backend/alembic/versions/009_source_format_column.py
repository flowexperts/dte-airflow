"""promote source `format` from config JSONB to a first-class column

The filesystem-family loader ("filesystem" / "s3" / "gcs" / "azure")
carried an optional `format` override inside the JSONB `config` blob to
override extension-based detection (`.json`, `.csv`, `.xlsx`, etc.).
Hiding it in JSONB made it hard to introspect and made the model
config's `extra: "forbid"` fight the schema.

This migration:
  1. Adds a nullable `sources.format` column.
  2. Backfills each row's value from `config->>'format'`.
  3. Strips `format` from `config` so it lives in exactly one place.

Nulls after backfill mean "auto-detect from extension" — same semantics
as before.

Revision ID: 009
Revises: 008
Create Date: 2026-07-17
"""
from alembic import op


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sources ADD COLUMN IF NOT EXISTS format TEXT")
    op.execute(
        "UPDATE sources "
        "SET format = config->>'format' "
        "WHERE config ? 'format' "
        "  AND (format IS NULL OR format = '')"
    )
    op.execute("UPDATE sources SET config = config - 'format' WHERE config ? 'format'")


def downgrade() -> None:
    # Push it back into config so the pre-009 code path still works.
    op.execute(
        "UPDATE sources "
        "SET config = jsonb_set(config, '{format}', to_jsonb(format)) "
        "WHERE format IS NOT NULL"
    )
    op.execute("ALTER TABLE sources DROP COLUMN IF EXISTS format")
