"""Rename destination config types to format-only names.

Output targets used to pin a format to one location: `json_file` meant
"JSON, on local disk" and `parquet_s3` meant "Parquet, on S3". Format and
location are now independent axes — any format writes to any of local_fs /
s3 / gcs / azure — so the discriminator names the format only:

    json_file  -> json
    csv_file   -> csv
    excel_file -> excel
    parquet_s3 -> parquet

`parquet_s3` also carried its path under `bucket_url`; that is renamed to
`path` so every file target shares one field name. The model still accepts
`bucket_url` as an input alias, and `_canonicalise_dest_type` still accepts
the legacy `type` values, so a row missed by this migration (or written by
an older node mid-deploy) keeps parsing.

`destinations` is a small config table — one row per configured output — so
a plain UPDATE is appropriate here rather than `batched_update`.

Revision ID: 028
Revises: 027
Create Date: 2026-08-04
"""
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None

_RENAMES = {
    "json_file": "json",
    "csv_file": "csv",
    "excel_file": "excel",
    "parquet_s3": "parquet",
}


def upgrade() -> None:
    for old, new in _RENAMES.items():
        op.execute(f"""
            UPDATE destinations
               SET config = jsonb_set(config, '{{type}}', '"{new}"')
             WHERE config->>'type' = '{old}'
        """)
    # parquet_s3 stored its location under `bucket_url`; unify on `path`.
    op.execute("""
        UPDATE destinations
           SET config = (config - 'bucket_url')
                        || jsonb_build_object('path', config->'bucket_url')
         WHERE config->>'type' = 'parquet'
           AND config ? 'bucket_url'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE destinations
           SET config = (config - 'path')
                        || jsonb_build_object('bucket_url', config->'path')
         WHERE config->>'type' = 'parquet'
           AND config ? 'path'
    """)
    for old, new in _RENAMES.items():
        op.execute(f"""
            UPDATE destinations
               SET config = jsonb_set(config, '{{type}}', '"{old}"')
             WHERE config->>'type' = '{new}'
        """)
