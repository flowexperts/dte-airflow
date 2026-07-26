# Plan 027 — P0…P4 priority ladder

**Context.** A Head-of-Engineering-style review (July 2026) produced a punch list of gaps against a data-platform standards bar. This plan pins the ladder in-repo so future rounds can reference item numbers, mark them off, and see what's still open. It supersedes the ad-hoc lists that lived only in Claude conversations.

Priority ladder:
- **P0** — pre next customer
- **P1** — pre GA
- **P2** — scale-driven
- **P3** — platform-hardening
- **P4** — differentiator

Status: ✅ done · 🟡 partial · ⬜ not started.

Snapshot commit: main after merges of P1 #18, P1 #21, P3 #32, P3 #33, P3 #35 (2026-07-23).

---

## P0 — pre next customer

| # | Item | Status | Where |
| - | - | - | - |
| 1 | GitHub Actions CI (backend + frontend + e2e job) | ✅ | `.github/workflows/ci.yml` |
| 2 | Structured logging + request-ID middleware | ✅ | `dte/logging.py`, `dte/api/middleware.py` |
| 3 | Typed exception hierarchy + global handlers | ✅ | `dte/errors.py`, `dte/api/error_handlers.py` |
| 4 | Run guardrails (timeout, cancel, max_rows) | ✅ | `dte/runs.py`, `_execute_pipeline` in `dte/api/routes/pipelines.py` |
| 5 | Frontend `error.tsx` + toast surface | ✅ | `frontend/src/app/error.tsx`, `components/toaster.tsx` |
| 6 | Pydantic `BaseSettings` | ✅ | `dte/config.py` |
| 7 | Prettier / husky / lint-staged | ✅ | `frontend/.prettierrc`, `frontend/.husky/pre-commit` |
| 8 | `/healthz` + `/readyz` + Docker healthcheck | ✅ | `dte/api/routes/health.py`, `docker-compose.yml` |
| 9 | Migrate env reads → Settings (JWT, secrets, admin) | ✅ | `dte/security/jwt.py`, `dte/secrets/__init__.py`, `dte/admin/__init__.py` |
| 10 | Ruff + Ruff-in-CI | ✅ | `[tool.ruff]` in `backend/pyproject.toml` |
| 11 | Compiler error-path tests | ✅ | `backend/tests/unit/test_compiler_errors.py` (8 tests) |
| 12 | Secrets rotation script | ✅ | `backend/scripts/rotate_secrets_key.py` |
| 13 | Coverage floor in CI | ✅ | `--cov-fail-under=70` (current 77%) |

**P0 rollup: 13/13 done.**

---

## P1 — pre GA

| # | Item | Status | Where |
| - | - | - | - |
| 14 | OpenTelemetry spans per pipeline stage | ✅ | `dte/tracing.py`; spans in `_run_body` (resolve/load/compile/write). Opt-in via `DTE_TRACING_ENABLED=1`. |
| 15 | Per-step run events + Timeline UI | ✅ | migration `013_run_events.py`, `RunEventStore`, `GET /api/runs/{id}/events`, Timeline wired in `runs/[id]/page.tsx` |
| 16 | Streaming writers (json / csv / parquet / excel) | ✅ | all four now stream via DuckDB `COPY` or PyArrow `ParquetWriter` batches |
| 17 | Playwright smoke suite | ✅ scaffold + e2e CI job | `frontend/playwright.config.ts`, `frontend/e2e/smoke.spec.ts`. Not yet executed against a live stack. |
| 18 | Docker productionisation | ✅ | healthcheck ✅ · non-root `dte` user ✅ · CPU/mem limits ✅ (all three services) · Trivy scan ✅ (dev + prod stages) · `curl` removed ✅ · in-Dockerfile HEALTHCHECK ✅ · distroless runtime ✅ (`backend/Dockerfile.prod`, `dte/docker/entrypoint.py`, `docker/distroless-libs.txt`). |
| 19 | Hypothesis property tests on compiler | ✅ | `test_compiler_hypothesis.py`; 1 property (random rename/select/sort composition). Caught real rename-validation bug. |
| 20 | `noUncheckedIndexedAccess` sweep | ✅ | `frontend/tsconfig.json` flipped, 30 errors → 0 |
| 21 | Secrets rotation runbook (docs) | ✅ | `docs/runbooks/secrets-rotation.md` (163 lines); references `backend/scripts/rotate_secrets_key.py` from P0 #12 |

**P1 rollup: 8/8 done.** (distroless base shipped: `backend/Dockerfile.prod` + `dte/docker/entrypoint.py`; plan 036 complete.)

---

## P2 — scale-driven

Each item wants a dedicated `plans/<N>-*.md` before code.

| # | Item | Status | Notes |
| - | - | - | - |
| 22 | Connection pooling (Mongo / dlt / DuckDB scanner) | ✅ | `dte/sources/pools/{mongo,engine}.py` — keyed pool, evicted on connection PUT/DELETE, closed via FastAPI lifespan. dlt-pipeline pool carried as follow-up in plan 028. |
| 23 | Data-quality contracts | ✅ | `dte/models/quality.py` + `dte/quality/evaluator.py`. Contracts: row_count_between, column_not_null, column_unique, column_in_range, column_matches. New terminal statuses `completed_with_warnings` / `failed_quality`. `GET /api/runs/{id}/quality`. Plan: `plans/029`. |
| 24 | Multi-tenant isolation review | ✅ | migrations `015_tenant_id.py` + `016_rls_policies.py` + `017_tenant_secret_keys.py`. `tenant_id` on every tenant-scoped model + fake, JWT `tenant` claim, `get_current_tenant_id` dep, per-tenant Fernet keys via `tenant_secret_keys`. `DTE_MULTI_TENANT_ENABLED` gates route-side enforcement. **Middleware wired (2026-07-25):** `dte/tenancy.py` (contextvar helpers), `TenantContextMiddleware` in `dte/api/middleware.py` (decodes JWT, sets contextvar, 401 on protected paths), `_open_tenant_session()` in `dte/store/postgres.py` (issues `SET LOCAL dte.tenant_id` on every Postgres session), `copy_context()` in `trigger_pipeline` propagates tenant into background task. Plan: `plans/030`. |
| 25 | Distributed execution seam (Spark / Trino backend) | ✅ | `dte/engine/{base,trino_engine,registry}.py`; `Pipeline.engine: Literal["duckdb","trino"]`, dispatched via `get_engine()` and gated behind `DTE_TRINO_ENABLED`. Raw-SQL escape hatches raise `TrinoRawSqlNotSupported`; pivot xfailed with reason. Plan: `plans/034`. |
| 26 | Frontend perf pass | ✅ | `@next/bundle-analyzer` wired (`pnpm analyze`); 6 list/detail routes retired `force-dynamic` for `revalidate = 30`; edit pages kept dynamic; font audit landed (dropped Outfit weight 300 + Cormorant `normal` style — both unused). Baseline first-load JS measurement carried in `plans/033-frontend-perf-pass.md` — run `pnpm analyze` before/after next FE landing to record numbers. |
| 27 | `exactOptionalPropertyTypes` (next TS strictness flag) | ✅ | `frontend/tsconfig.json` flipped, 8 errors → 0. Widened `?: T` → `?: T \| undefined` on DataTable, FieldPicker, FieldTreePicker, Field, FieldNode, and CredentialFields.StringField primitives. |

---

## P3 — platform-hardening

Wanted once >2 engineers ship weekly and customer volumes matter.

| # | Item | Status | Where |
| - | - | - | - |
| 28 | SLO/SLI definitions + Grafana/Datadog dashboards | ✅ | `docs/observability/slos.md` — 4 SLOs (99.5% run success, <60s p95 run, 99.9% API availability, <300ms API p95) with Prom expressions + error-budget policy |
| 29 | On-call runbook, top-5 failure-mode playbook | ✅ | `docs/runbooks/on-call.md` |
| 30 | Prometheus RED metrics on HTTP + domain metrics (rows/min, load-time by source_type) | ✅ | Domain metrics ✅ (`dte/metrics.py`); HTTP RED metrics via hand-rolled `dte/api/http_metrics.py::HttpMetricsMiddleware` (route template resolved from Starlette router; sidesteps `prometheus-fastapi-instrumentator` FastAPI 0.115+ crash). Both surface on `/metrics`. |
| 31 | Mutation testing (mutmut) on compiler | ✅ | `[tool.mutmut]` in `backend/pyproject.toml`; `.github/workflows/mutation.yml` (push-to-main only, non-blocking); `docs/testing/mutation.md` local usage doc |
| 32 | Dependency pinning + lockfile + Renovate/dependabot | ✅ | upper bounds on all direct deps in `backend/pyproject.toml`; root `uv.lock` committed; `backend/uv.lock` deleted (workspace uses root lock); CI uses `uv sync --frozen --extra dev` (setup-uv@v5); `pnpm install --frozen-lockfile` already in CI; `.github/renovate.json` (`config:base`, weekend schedule, grouped minor+patch per manager, majors separated) |
| 33 | Bandit / semgrep / pip-audit / gitleaks / Trivy in CI | ✅ | `.github/workflows/security.yml` (bandit, pip-audit, gitleaks, pnpm-audit) + `.github/workflows/trivy.yml` (image scan). semgrep still ⬜ |
| 34 | Alembic backfill pattern with batched UPDATEs | ✅ | `backend/dte/alembic_util.py::batched_update` (AUTOCOMMIT + FOR UPDATE SKIP LOCKED); CLAUDE.md now mandates for backfills > 100k rows. Spec: `plans/032-batched-alembic-backfills.md` |
| 35 | ARCHITECTURE.md + deployment runbook (outside CLAUDE.md) | ✅ | `ARCHITECTURE.md` at repo root (285 lines) |
| 36 | Audit log for credential decrypts | ✅ | `EncryptedJSON.process_result_value` emits `event=credential_decrypt` on `dte.audit.credentials` logger with request_id + user_id + decrypt_context (`reveal_api` / `connection_read` / `connection_test` / `pipeline_preview` / `pipeline_run` / `unknown`). Persistence-table variant deferred; log platform is authoritative for MVP. |
| 37 | Rate limiting on auth endpoints | ✅ | slowapi @ 5/minute per-IP on `/api/auth/login` + `/api/auth/register`; shared limiter in `backend/dte/api/limiter.py`; tests in `tests/unit/test_rate_limit.py` |

---

## P4 — differentiator

Product-shape bets; each is its own initiative.

| # | Item | Status |
| - | - | - |
| 38 | Streaming source support (CDC, Kafka, webhooks) | ⬜ plan | sequenced in `plans/035-p4-differentiator-roadmap.md` (5th priority) |
| 39 | Embedded pipeline SDK for external callers | 🟡 | workspace scaffolded (`packages/dte-sdk`, plan 025); sequenced 2nd in `plans/035-*` |
| 40 | Plugin / step marketplace | ⬜ plan | sequenced 6th (kill-condition candidate) in `plans/035-*` |
| 41 | AI-assisted pipeline authoring | ⬜ plan | sequenced 4th in `plans/035-*`, depends on #43 + #39 |
| 42 | Cost visibility per pipeline / per run | ⬜ plan | sequenced 3rd in `plans/035-*`, builds on plan 031 metrics |
| 43 | Version-controlled pipeline history + diff view | ✅ | migration `014` + `PipelineRevision` model/store; `_record_revision` on POST/PUT with summary from `dte/pipelines/diff.py`; runs pin `revision_id` at trigger. GET `/api/pipelines/{id}/revisions{,/{id},/diff}` return typed history + structured diff. Frontend: History section on pipeline detail (`components/builder/history/HistoryPanel.tsx` + `DiffView.tsx`) + revision short-hash link on run detail. Spec: `plans/037-pipeline-history-and-diff.md`. |

---

## Verification (how to keep this file honest)

- Update the ✅/🟡/⬜ column any time a numbered item lands or slips.
- When an item moves to "in progress," add its dedicated plan file to `plans/` and link it in the row's "Where" / "Notes" column.
- Snapshot commit line at the top gets bumped when the roadmap is re-audited.
- Do NOT edit item numbers — they're referenced by commit messages, PRs, and Claude conversations. Add new items at the end of the priority tier they belong to.

## Critical files this plan touched (read-only reference)

- `.github/workflows/ci.yml`
- `backend/dte/{config,logging,errors,runs,tracing}.py`
- `backend/dte/api/{main,middleware,error_handlers,deps}.py`
- `backend/dte/api/routes/{pipelines,runs,health}.py`
- `backend/dte/compiler/ibis_compiler.py`
- `backend/dte/engine/writers/*`
- `backend/dte/store/{base,postgres}.py`
- `backend/dte/secrets/*`, `backend/dte/security/jwt.py`
- `backend/alembic/versions/013_run_events.py`
- `backend/scripts/rotate_secrets_key.py`
- `backend/tests/unit/test_compiler_{errors,hypothesis}.py`, `test_run_events{,_api}.py`
- `frontend/tsconfig.json`, `frontend/src/components/{ui/field-tree.ts,builder/steps/*}`
- `frontend/src/app/{error.tsx,layout.tsx}`, `components/toaster.tsx`
- `frontend/playwright.config.ts`, `frontend/e2e/smoke.spec.ts`
- `docker-compose.yml` (resource limits on all three services)
- `backend/Dockerfile.prod` (distroless multi-stage build)
- `backend/dte/docker/entrypoint.py` (shell-free entrypoint for distroless)
- `backend/docker/distroless-libs.txt` (libpq closure catalogue)
- `.github/workflows/trivy.yml` (now scans both dev + prod images)
