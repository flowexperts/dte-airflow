"""Bind a schedule to an eval set (plan 051 phase 5).

One nullable column on `schedules`. The runner reads `eval_set_id` off the
*run* row; the trigger route stamps it there, and until now the ticker had
no value to stamp — so every scheduled eval run failed with "eval pipeline
triggered without an eval_set_id". Nightly regression detection, already
written and Wilson-gated, was unreachable.

Nullable with no default, for the same reason the `runs` eval columns are:
an ordinary transform schedule has no eval identity, and a non-null
sentinel would make "not an eval schedule" indistinguishable from "an eval
schedule pointing at nothing".

No foreign key on purpose. The API refuses (409) to delete an eval set a
schedule still references, naming the schedules — the contract sources and
destinations already use. A `CASCADE` would delete a user's schedule as a
silent side effect of deleting an eval set, and `SET NULL` would leave a
schedule that fires nightly and fails every time.

Revision ID: 035
Revises: 034
"""
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE schedules ADD COLUMN IF NOT EXISTS eval_set_id TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE schedules DROP COLUMN IF EXISTS eval_set_id")
