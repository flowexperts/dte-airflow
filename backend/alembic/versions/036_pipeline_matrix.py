"""The comparison matrix belongs to the eval pipeline (plan 055).

One nullable JSONB column on `pipelines`: dotted axis path → the values to
vary, e.g. `{"provider": ["claude", "regex"]}`.

The matrix used to exist only inside the Compare wizard — posted once to
`POST /eval-sets/{id}/sweep` and never stored. So a comparison could not be
reopened, adjusted and re-run: you started from an empty form and minted a
fresh set of variant pipelines each time, which is how one demo pipeline
accumulated twelve variants.

Nullable with no default, matching the `runs` eval columns and
`schedules.eval_set_id`: absent means N=1, an ordinary single-config eval
run, and that is the nightly regression check rather than a degenerate
comparison. A `'{}'::jsonb` default would erase the difference between "not
a comparison" and "a comparison with nothing configured".

No backfill. Every existing pipeline is correctly N=1 — none of them had a
matrix to keep, because there was nowhere to put one.

Revision ID: 036
Revises: 035
"""
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS matrix JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE pipelines DROP COLUMN IF EXISTS matrix")
