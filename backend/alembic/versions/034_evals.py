"""Eval harness storage (plan 051 task 1).

Two new tables plus five columns on `runs`.

`eval_examples` is keyed on `(eval_set_id, doc_key)` by a UNIQUE constraint,
not just by its primary key. `doc_key` is `sha256(document bytes)` — the same
key the plan-050 artifact store uses — and the natural identity of a label is
the document it labels. Without the constraint, relabeling a document appends
a second, contradictory row and the corpus is then scored against both.

`ON DELETE CASCADE` on `eval_set_id`: deleting a set must not leave orphaned
labels that no longer join to any field spec.

The `runs` columns are nullable with no default. A transform run has no eval
identity, and writing `''`/`0` instead of NULL would make "never scored"
indistinguishable from "scored zero" — the exact confusion the harness exists
to prevent. No backfill: existing rows are correctly NULL.

`ix_runs_eval_set_id` is partial on `eval_set_id IS NOT NULL` — the
leaderboard's only read path, and eval runs will always be a small minority of
the `runs` table.

Tenant pattern follows migration 032: `tenant_id NOT NULL DEFAULT 'default'`,
`ENABLE` + `FORCE ROW LEVEL SECURITY`, `tenant_isolation` policy.

Revision ID: 034
Revises: 033
Create Date: 2026-08-13
"""
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS eval_sets (
            id             TEXT PRIMARY KEY,
            tenant_id      TEXT NOT NULL DEFAULT 'default',
            name           TEXT NOT NULL,
            source_id      TEXT NOT NULL,
            field_specs    JSONB NOT NULL DEFAULT '[]',
            labels_version INTEGER NOT NULL DEFAULT 1,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_eval_sets_tenant_id ON eval_sets (tenant_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS eval_examples (
            id             TEXT PRIMARY KEY,
            tenant_id      TEXT NOT NULL DEFAULT 'default',
            eval_set_id    TEXT NOT NULL REFERENCES eval_sets(id) ON DELETE CASCADE,
            doc_key        TEXT NOT NULL,
            doc_ref        TEXT,
            labels         JSONB NOT NULL DEFAULT '{}',
            label_source   TEXT NOT NULL DEFAULT 'human',
            split          TEXT NOT NULL DEFAULT 'train',
            labels_version INTEGER,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_eval_examples_set_doc UNIQUE (eval_set_id, doc_key)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_eval_examples_set_split "
        "ON eval_examples (eval_set_id, split)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_eval_examples_tenant_id ON eval_examples (tenant_id)"
    )

    for table in ("eval_sets", "eval_examples"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('dte.tenant_id', true)::text)
        """)

    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS eval_set_id TEXT")
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS labels_version INTEGER")
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS config_digest TEXT")
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS sweep_id TEXT")
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS scores JSONB")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_runs_eval_set_id ON runs (eval_set_id) "
        "WHERE eval_set_id IS NOT NULL"
    )
    # Drift detection reads "the previous run at this digest" — same config,
    # same labels, different day. Without this index that is a seq scan of
    # every run in the table on every nightly eval.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_runs_config_digest "
        "ON runs (config_digest, started_at DESC) WHERE config_digest IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_runs_sweep_id ON runs (sweep_id) "
        "WHERE sweep_id IS NOT NULL"
    )

    # Grant the new permissions to the roles migration 012 seeded. Adding a
    # value to `Permission` in the code only changes what *may* be checked —
    # the roles table holds what is actually granted, so without this an
    # existing admin gets a 403 on every eval route.
    op.execute(
        "UPDATE roles SET permissions = permissions || "
        "ARRAY['eval:read', 'eval:write', 'eval:delete']::text[] "
        "WHERE id = 'admin' AND NOT ('eval:read' = ANY(permissions))"
    )
    op.execute(
        "UPDATE roles SET permissions = permissions || "
        "ARRAY['eval:read', 'eval:write']::text[] "
        "WHERE id = 'editor' AND NOT ('eval:read' = ANY(permissions))"
    )
    op.execute(
        "UPDATE roles SET permissions = permissions || ARRAY['eval:read']::text[] "
        "WHERE id = 'viewer' AND NOT ('eval:read' = ANY(permissions))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE roles SET permissions = ARRAY("
        "  SELECT p FROM unnest(permissions) AS p WHERE p NOT LIKE 'eval:%'"
        ")::text[]"
    )
    op.execute("DROP INDEX IF EXISTS ix_runs_sweep_id")
    op.execute("DROP INDEX IF EXISTS ix_runs_config_digest")
    op.execute("DROP INDEX IF EXISTS ix_runs_eval_set_id")
    for col in ("scores", "sweep_id", "config_digest", "labels_version", "eval_set_id"):
        op.execute(f"ALTER TABLE runs DROP COLUMN IF EXISTS {col}")

    for table in ("eval_examples", "eval_sets"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS eval_examples")
    op.execute("DROP TABLE IF EXISTS eval_sets")
