# CLAUDE.md

Guidance for Claude Code in this repo. Area-specific rules live in
path-scoped `CLAUDE.md` files that load automatically when you touch that
directory:

```
frontend/CLAUDE.md            Next 16, design system, builder (+ DESIGN.md, AGENTS.md)
backend/CLAUDE.md             data flow, compiler, ibis, field refs, extract/structure
backend/dte/api/CLAUDE.md     HTTP surface
backend/dte/evals/CLAUDE.md   eval sets, sweeps, comparison, promote, matrix
backend/dte/sources/CLAUDE.md sources, destinations, connections, credentials
backend/dte/store/CLAUDE.md   stores, SQLModel, Alembic
backend/tests/CLAUDE.md       testing tiers
docs/worktrees.md             worktree + compose setup (read before the first run)
```

## Repo layout

```
backend/       Python package `dte`, alembic, tests, Dockerfile
frontend/      Next.js app
docker-compose.yml   whole stack (postgres + backend + frontend)
plans/         feature plans (numbered)
marketing-plans/  go-to-market plans (numbered) — ICP, motion, pricing, content
```

All Python paths below are relative to `backend/`.

## Commands

```bash
# Whole stack (postgres :5432, backend :8001, frontend :3000), hot reload
docker compose up -d --build
docker compose logs -f backend

# Backend
cd backend && uv venv && uv pip install -e ".[dev]"
uv run pytest                      # unit; scenarios excluded by default
uv run pytest tests/scenarios -m scenario -v
uv run pytest -m "not integration" # skip postgres tests
uv run uvicorn dte.api.main:app --port 8001 --reload
uv run alembic upgrade head        # needs sync DATABASE_URL

# Frontend
cd frontend && pnpm install && pnpm dev
DTE_API_URL=http://localhost:8001 ./scripts/gen-api-types.sh   # regen types
```

Backend is on **:8001** (an unrelated Django server squats on :8000 here).

## Architecture in one paragraph

DTE is a batch data transformation engine. A **Pipeline** (Pydantic) names
sources, ordered transform steps and an output. Sources load into a shared
DuckDB connection as ibis tables (`dte/sources/loader.py`), the compiler
(`dte/compiler/ibis_compiler.py`) folds steps over a named table registry, and
`dte/engine/duckdb_engine.py` executes and writes. Persistence is
Postgres-only (`dte/store/`); tests inject fakes. Details in
`.claude/rules/architecture.md`.

## Development workflow

**Before implementing any feature**, write a plan to
`plans/<NNN>-<feature-name>.md`: problem statement, architecture change,
explicit task list with branch names, files changed/deleted. Go-to-market
plans go in `marketing-plans/` instead (no branch names or task lists).

**Every non-trivial change gets its own worktree. Do not develop on `main`.**

```bash
git worktree add ./worktrees/<name> -b feature/<name>
cd worktrees/<name>/backend && uv run pytest -x
git merge feature/<name> --no-ff
git worktree remove worktrees/<name> && git branch -d feature/<name>
```

A fresh worktree needs four setup steps and compose must be run *from* it —
see `.claude/rules/worktrees.md` before the first run.

## TDD convention

Write failing tests first. Implement until they pass. Stop — do not add
features beyond what tests require.
