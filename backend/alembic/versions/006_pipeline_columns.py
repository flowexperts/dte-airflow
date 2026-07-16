"""reshape pipelines: unpack `definition` blob into sources/steps/output_id columns

Revision ID: 006
Revises: 005
Create Date: 2026-07-15
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS sources   JSONB")
    op.execute("ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS steps     JSONB")
    op.execute("ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS output_id TEXT")

    op.execute("""
        UPDATE pipelines SET
            sources   = COALESCE(definition->'sources', '[]'::jsonb),
            steps     = COALESCE(definition->'steps',   '[]'::jsonb),
            output_id = definition->>'output_id'
        WHERE definition IS NOT NULL
    """)

    op.execute("ALTER TABLE pipelines ALTER COLUMN sources   SET NOT NULL")
    op.execute("ALTER TABLE pipelines ALTER COLUMN steps     SET NOT NULL")
    op.execute("ALTER TABLE pipelines ALTER COLUMN output_id SET NOT NULL")
    op.execute("ALTER TABLE pipelines DROP COLUMN IF EXISTS definition")


def downgrade() -> None:
    op.execute("ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS definition JSONB")
    op.execute("""
        UPDATE pipelines SET definition = jsonb_build_object(
            'id', id,
            'name', name,
            'sources', sources,
            'steps', steps,
            'output_id', output_id
        )
    """)
    op.execute("ALTER TABLE pipelines ALTER COLUMN definition SET NOT NULL")
    op.execute("ALTER TABLE pipelines DROP COLUMN IF EXISTS output_id")
    op.execute("ALTER TABLE pipelines DROP COLUMN IF EXISTS steps")
    op.execute("ALTER TABLE pipelines DROP COLUMN IF EXISTS sources")
