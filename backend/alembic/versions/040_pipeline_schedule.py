"""One pipeline, one schedule, one DAG (plan 068).

The schedule moves onto the pipeline as `pipelines.schedule` JSONB, so it is
part of the spec and every change to it is a revision — and a revision is a
DAG version. The `schedules` table goes.

A pipeline with several schedules keeps one: the most recently updated
enabled one, else the most recently updated. The ones dropped are printed.

Every pipeline that gained a schedule, or never had a revision, gets a new
revision built from its row, because the DAG factory builds each DAG from a
pipeline's latest revision.

Revision ID: 040
Revises: 039
"""
from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS schedule JSONB")
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT to_regclass('schedules')").scalar() is None:
        return

    op.execute("""
        CREATE TEMP TABLE _kept ON COMMIT DROP AS
        SELECT DISTINCT ON (pipeline_id) id, pipeline_id,
               jsonb_build_object(
                   'cron_expr', cron_expr, 'timezone', timezone, 'params', params,
                   'enabled', enabled, 'overlap', overlap, 'eval_set_id', eval_set_id
               ) AS schedule
          FROM schedules
         ORDER BY pipeline_id, enabled DESC, updated_at DESC NULLS LAST
    """)
    for sid, pid, cron in bind.exec_driver_sql(
        "SELECT id, pipeline_id, cron_expr FROM schedules WHERE id NOT IN (SELECT id FROM _kept)"
    ):
        print(f"040: dropped extra schedule {sid} ({cron!r}) of pipeline {pid}")

    op.execute("UPDATE pipelines p SET schedule = k.schedule FROM _kept k WHERE k.pipeline_id = p.id")
    op.execute("""
        INSERT INTO pipeline_revisions (id, pipeline_id, config, summary)
        SELECT gen_random_uuid()::text, p.id,
               to_jsonb(p) - 'created_at' - 'updated_at',
               'schedule moved onto the pipeline (plan 068)'
          FROM pipelines p
         WHERE p.id IN (SELECT pipeline_id FROM _kept)
            OR NOT EXISTS (SELECT 1 FROM pipeline_revisions r WHERE r.pipeline_id = p.id)
    """)
    op.execute("DROP TABLE schedules")


def downgrade() -> None:
    raise NotImplementedError("plan 068 folds schedules into pipelines; restore from backup")
