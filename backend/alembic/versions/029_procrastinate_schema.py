"""Install procrastinate's own schema (plan 046 task 1).

Procrastinate is a Postgres-backed job queue — the queue tables/functions/
types live in the same database as everything else, no new datastore. We
don't hand-write the DDL: `procrastinate.schema.SchemaManager.get_schema()`
returns the exact SQL the pinned `procrastinate` version ships (its own
`schema.sql`), so upgrading the dependency and re-running this pattern in a
future migration stays in lockstep with the library.

Downgrade drops every `procrastinate_*` object generically (functions via
`pg_proc` lookup so overloaded signatures don't need to be hand-enumerated,
tables/types via `CASCADE` so their triggers/indexes go with them).

Revision ID: 029
Revises: 028
Create Date: 2026-08-07
"""
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from procrastinate.schema import SchemaManager

    schema_sql = SchemaManager.get_schema()
    op.execute(schema_sql)


def downgrade() -> None:
    op.execute("""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN
                SELECT p.proname AS name, pg_get_function_identity_arguments(p.oid) AS args
                  FROM pg_proc p
                  JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate_%'
            LOOP
                EXECUTE format('DROP FUNCTION IF EXISTS %I(%s) CASCADE', r.name, r.args);
            END LOOP;
        END $$;
    """)
    op.execute("DROP TABLE IF EXISTS procrastinate_events CASCADE")
    op.execute("DROP TABLE IF EXISTS procrastinate_periodic_defers CASCADE")
    op.execute("DROP TABLE IF EXISTS procrastinate_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS procrastinate_workers CASCADE")
    op.execute("DROP TYPE IF EXISTS procrastinate_job_to_defer_v1 CASCADE")
    op.execute("DROP TYPE IF EXISTS procrastinate_job_event_type CASCADE")
    op.execute("DROP TYPE IF EXISTS procrastinate_job_status CASCADE")
