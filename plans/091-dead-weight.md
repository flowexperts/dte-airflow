# 091 — Delete what the Airflow cut left behind

## Problem

Migration 039 moved DTE onto Airflow. Code and docs from the earlier design
are still around:

- `tenant_id: str = "default"` is on every model (`backend/dte/models/pipeline.py:222,469,604,1097,1471`).
  The `Tenant` class is still in `models/tenant.py:24`, but 039 dropped the
  `tenants` table and RLS.
- `backend/dte/secrets/` holds only `__pycache__`.
  `ConnectionBase` credential validation against dlt configspecs is
  overridden to do nothing in `Connection`. The `pipeline.py:196` comment
  still mentions `EncryptedJSON`.
- The legacy 3-argument loader path guesses the connection type from the URL
  scheme (`backend/dte/sources/loader.py:450-500`).
- Eval, Visualize and dashboard UI ship in the bundle with no route. The
  bundle (`backend/ui/dte.umd.js`, 786 KB) isn't code-split, and loads
  recharts, pdfjs, marked and `@calcom/embed-react` on every DTE page.
- Stale docs: `backend/dte/sources/CLAUDE.md` describes Fernet resolvers and
  the three-tier encrypted connections, which contradicts
  `store/CLAUDE.md`. `gen-api-types.sh` is fixed in 088.
- Merged or stale worktrees: `dashboards`, `sdk-move-core`, `site-redo`,
  `tenant-session`, `.claude/worktrees/agent-af67dab5540b7e17d`, and
  `pypi-release` (0 commits ahead).
- `ee-split` is 91 commits behind and was written for the pre-Airflow design.

## Tasks

### 1. Backend dead code — `feature/091-backend-dead`
- Drop `tenant_id` (Alembic migration drops the columns), `models/tenant.py`,
  `secrets/`, the dead credential-validation code and the legacy loader
  signature. Find callers with ast-grep before deleting each one.
- `uv run pytest` green, `dte db upgrade` clean on a fresh DB.

### 2. Frontend dead code and split — `feature/091-fe-dead`
- Delete the unrouted eval, visualize and dashboard components, along with
  their deps if nothing else uses them.
- `React.lazy` per route entry in `plugin.tsx`. Measure the bundle before and
  after in the PR description.

### 3. Docs — same branch as 1
- Rewrite the connections section of `sources/CLAUDE.md` to match
  `store/CLAUDE.md` (Airflow owns connections).

### 4. Worktrees (no branch)
- `git worktree remove` plus `git branch -d` for the merged ones listed above.
  Confirm with `git log dte-airflow..<branch>` that each is empty first.

### 5. ee-split decision (no code)
- Either re-plan the open-core split on top of Airflow auth (roles come from
  Airflow's auth manager now) as a new numbered plan, or delete the branch.
  Rebasing it isn't worth it.

## Files

Deleted: `backend/dte/models/tenant.py`, `backend/dte/secrets/`, unrouted
frontend components.

Changed: `backend/dte/models/pipeline.py`, `backend/dte/sources/loader.py`,
`backend/dte/sources/CLAUDE.md`, `frontend/src/plugin.tsx`,
`frontend/package.json`.

New: one Alembic migration.
