# Worktrees

### Setting up a fresh worktree

A new worktree is a checkout of tracked files only, so everything ignored or
generated is missing. Four things, and each fails in a way that does not name
the real cause:

```bash
cd worktrees/<name>
cp ../../.env .                      # 1
cd frontend && pnpm install          # 2
pnpm exec next typegen               # 3
cd ../backend && uv venv && uv pip install -e ".[dev]"   # 4
```

1. **`.env` is gitignored, so a new worktree has none.** Compose reads `.env`
   from the directory you invoke it in — not from the repo root — so a stack
   started in a fresh worktree comes up with nothing set and the backend dies
   on `RuntimeError: DTE_JWT_SECRET must be set when DATABASE_URL is set
   (production)`. The message describes the symptom, not the cause: the file
   is simply absent. `.env.example` is committed; the real one is not.
   Copy it, and never commit the copy — `.gitignore:13` covers `.env` but
   **not** `.env.*`, so a `.env.bak` is a secrets file git can see.
2. Missing `node_modules` surfaces as `Cannot find module 'pdfjs-dist'` from
   `tsc` — which reads as a broken import, not a missing install. The same
   applies to any checkout whose `node_modules` predates a new dependency,
   `main` included.
3. No venv means `uv run pytest` fails with `Failed to spawn: pytest`. The
   `[dev]` extra does **not** pull `trino`, so a fresh venv fails 6 tests in
   `tests/unit/test_engine_seam.py` that read as a Trino regression and are
   not one — `uv pip install "ibis-framework[trino]"` fixes them.

### Docker from a worktree

**Always run compose from the worktree you are working in**, and keep
`-p dte` so the `dte_pgdata` and `dte_artifacts` volumes are reused:

```bash
cd worktrees/<name> && docker compose -p dte up -d
```

Compose bind-mounts `./backend/dte`, `./backend/alembic` and `./frontend`
**relative to the invocation directory**, so the directory you type this in
decides which code runs. Two ways that bites:

- Starting the stack from a directory whose `alembic/versions` lags the
  database fails with `Can't locate revision identified by '0NN'` and the
  backend exits — alembic walks *forward* from the DB's current revision, and
  a revision the script directory has never heard of is unreachable. Running
  from `main` while the DB is at a feature branch's migration does this.
- A stack left running from another directory silently serves *that* code.
  The frontend is the confusing one: features vanish from the UI with no
  error anywhere.

`docker inspect <container> --format '{{index .Config.Labels
"com.docker.compose.project.working_dir"}}'` says which directory a running
container was started from — check it first when the UI and the code
disagree.

