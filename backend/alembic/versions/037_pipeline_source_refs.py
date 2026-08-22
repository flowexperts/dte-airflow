"""Pipeline sources become table refs, not bare ids (plan 056).

`Pipeline.sources` changes shape from `list[str]` (bare source ids) to
`list[SourceTableRef]` (`{source_id, table, alias}`), so a pipeline can pick
several tables off one `sql_database` Source instead of needing a separate
Source row per table. `SqlDatabaseSourceConfig` drops its own `table` key —
which table is read is now a per-pipeline-per-use decision on the ref, not
part of the source's config.

This is a **clean break**, not a lossy auto-conversion: a bare source id
carries no table name and no sane default alias to backfill (`alias =
source_id` is a fine default for filesystem/mongo/etc, but every
`sql_database` ref in an existing pipeline would need a table this
migration has no way to know). So every pipeline and pipeline revision is
deleted outright rather than guessed at.

`runs.revision_id` has `ON DELETE SET NULL` (migration 014), so historical
runs survive with their `revision_id` nulled — only the pipeline/revision
rows themselves go.

No `batched_update` here: `pipelines` and `pipeline_revisions` are
per-tenant config tables, not event/fact tables — row counts stay in the
hundreds to low thousands even for large deployments, nowhere near the
100k-row threshold that rule exists for (plan 032).

Revision ID: 037
Revises: 036
"""
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # runs.revision_id has ON DELETE SET NULL (migration 014), but
    # runs.pipeline_id is a plain FK with no cascade (migration 001) — it
    # would block this delete outright. Runs are meant to survive as
    # orphaned history (run-detail tolerates a missing pipeline), so the
    # constraint is dropped rather than the rows being deleted too.
    op.execute("ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_pipeline_id_fkey")
    op.execute("DELETE FROM pipeline_revisions")
    op.execute("DELETE FROM pipelines")

    # Strip the now-invalid `table` key from every sql_database source's
    # config JSONB — SqlDatabaseSourceConfig is `extra="forbid"`, so a
    # leftover `table` key would reject the row the next time it's saved
    # (e.g. via the source editor) even though nothing here changed its id.
    op.execute(
        """
        UPDATE sources
        SET config = config - 'table'
        WHERE source_type = 'sql_database' AND config ? 'table'
        """
    )


def downgrade() -> None:
    # Deleted rows are gone; nothing to restore. The config strip is not
    # reversible either (the original table name isn't kept anywhere) —
    # this migration is one-way by design, matching the clean break it
    # documents.
    pass
