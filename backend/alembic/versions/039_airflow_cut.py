"""DTE as an Airflow app (plan 065): drop orchestration, add run_results.

Runs, run_events, connections, users/roles/tenants and the schedule runtime
columns are gone — Airflow owns run history, connections and auth. What DTE
keeps per run (scores, quality, sql, events) lives in `run_results`, keyed by
the Airflow dag run id. Everything here runs in the `dte` schema (env.py sets
search_path), so Airflow's own tables are never touched.

Revision ID: 039
Revises: 038
"""
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Row-level security was tenancy; tenancy is dropped, and FORCE RLS with an
    # unset session var hides every row. Turn it off everywhere in this schema.
    op.execute("""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN SELECT policyname, tablename FROM pg_policies WHERE schemaname = current_schema()
            LOOP
                EXECUTE format('DROP POLICY IF EXISTS %I ON %I', r.policyname, r.tablename);
            END LOOP;
            FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = current_schema()
            LOOP
                EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', r.tablename);
                EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', r.tablename);
            END LOOP;
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS run_results (
            run_id        TEXT PRIMARY KEY,
            dag_id        TEXT NOT NULL,
            pipeline_id   TEXT NOT NULL,
            revision_id   TEXT,
            status        TEXT,
            error         TEXT,
            rows_written  BIGINT,
            location      TEXT,
            params        JSONB,
            quality_checks JSONB NOT NULL DEFAULT '[]',
            sql_query     JSONB,
            scores        JSONB,
            eval_set_id   TEXT,
            labels_version INTEGER,
            config_digest TEXT,
            sweep_id      TEXT,
            events        JSONB NOT NULL DEFAULT '[]',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    for col in ("pipeline_id", "eval_set_id", "sweep_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_run_results_{col} ON run_results ({col})")

    op.execute("DROP FUNCTION IF EXISTS runs_set_finished_at() CASCADE")
    for t in ("run_events", "runs", "user_roles", "roles", "users",
              "tenant_secret_keys", "tenants", "connections"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    # Leftovers from the procrastinate queue on installs that ran migration 029.
    op.execute("""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN
                SELECT p.proname AS name, pg_get_function_identity_arguments(p.oid) AS args
                  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate_%'
            LOOP
                EXECUTE format('DROP FUNCTION IF EXISTS %I(%s) CASCADE', r.name, r.args);
            END LOOP;
        END $$;
    """)
    for t in ("procrastinate_events", "procrastinate_periodic_defers",
              "procrastinate_jobs", "procrastinate_workers"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for ty in ("procrastinate_job_to_defer_v1", "procrastinate_job_event_type",
               "procrastinate_job_status"):
        op.execute(f"DROP TYPE IF EXISTS {ty} CASCADE")

    op.execute("DROP INDEX IF EXISTS ix_schedules_due")
    for c in ("next_run_at", "last_run_id", "last_fired_at"):
        op.execute(f"ALTER TABLE schedules DROP COLUMN IF EXISTS {c}")


def downgrade() -> None:
    raise NotImplementedError("plan 065 is a hard cut; restore from backup")
