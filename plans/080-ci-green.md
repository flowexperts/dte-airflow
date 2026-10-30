# 080 — Get CI and Security green on flowexperts/dte-airflow

## Problem

`CI` and `Security` fail on every push to `main` of the public repo. Red has
become normal, so a real failure would go unnoticed. Nothing is wrong with the
tests we can see; they never run, because lint fails first.

## What we keep

| Workflow | Trigger | Verdict |
|---|---|---|
| CI (backend tests, integration, frontend) | PR + push to main | **Keep.** The only test gate before a pip release. |
| Security · gitleaks | PR + push to main | **Keep.** The repo is public; history is readable. |
| Security · pip-audit, pnpm audit | PR + push to main | **Keep, move to weekly + manual.** A new CVE upstream shouldn't block an unrelated PR. |
| Security · bandit | PR + push to main | **Keep** with justified `# nosec`. |
| Deploy site | push to main | Keep (green). |
| PR gate | pull_request_target | Keep (works). |
| Mutation, Trivy | manual only | Keep; never block anything. |

Nothing is deleted.

## What's breaking and the fix

### 1. Backend lint — 91 ruff errors (`backend/dte`)

- 84 auto-fixable (UP037 quoted annotations, I001 import order, F401 unused
  imports, UP035, UP017, UP012): `uv run ruff check dte --fix`.
- 7 by hand:
  - `dte/sources/pools/mongo.py:21` F821 undefined `_MongoClient`: a real
    bug or a missing `TYPE_CHECKING` import. Check first.
  - `dte/airflow/trigger.py:18` B039 mutable `ContextVar` default: default to
    `None`, build the value at the call site.
  - B905 `zip()` without `strict=` in `api/routes/evals.py:1216`,
    `engine/writers/provenance.py:96`, `evals/runner.py:124`,
    `providers/pdf.py:193`: `strict=True` where lengths must match, otherwise
    `strict=False`, chosen per site.
  - `compiler/ibis_compiler.py:570` E741 `l`: rename.

### 2. Frontend lint — 29 eslint errors (`frontend/src`)

- 9 unused vars/imports (`BuilderForm.tsx:154 _drop`, `editors.tsx:25
  quoteString`, …): delete.
- 15 `react-hooks/set-state-in-effect`: e.g. `ScheduleForm.tsx:114,120`,
  `params-modal.tsx:99,104`, `compare-dialog.tsx:30`,
  `lookup-mappings-editor.tsx:27`, `pipeline-preview.tsx:115`,
  `editors.tsx:923,1665`. Most reset local state when a prop changes: use a
  `key` on the component, or derive the value during render. Where the effect
  syncs with something external, keep it and disable the rule on that line
  with a reason.
- 4 `react-hooks/refs` (`editors.tsx:793,805,1968,1972`): move the ref read
  into an effect or event handler.
- 1 `react-hooks/static-components` (`pipeline/steps-column.tsx:279`): hoist
  the component created at line 127 to module scope.
- These are behaviour-sensitive, so check each changed editor in the builder,
  not just with `pnpm test`.

### 3. Whatever lint was hiding

Once lint passes, unit, scenario, integration, `pnpm typecheck`, `pnpm test`
and `pnpm format:check` run in CI for the first time in a while. Run them
locally first and fix what fails; size unknown until then.

### 4. gitleaks — 1 finding, false positive

`scripts/test-pip-install.sh:17` (commit 0b132f3), `generic-api-key`. It is
the Azurite emulator's public, documented dev key, not a secret. Add the
finding's fingerprint to `.gitleaksignore`, with a comment saying what it is.

### 5. bandit — 10 medium findings

- 9 × B608 (SQL built with f-strings) in `compiler/ibis_compiler.py:669,676`,
  `engine/writers/_copy.py:73,120,122`, `engine/writers/provenance.py:83`, ….
  Check each one. Identifiers that come from pipeline config must be quoted
  (`sqlglot`/duckdb identifier quoting), and values must be bound parameters
  (e.g. `information_schema … WHERE table_name = ?`). Where the input is
  internal, add `# nosec B608` with the reason. Any real injection path gets a
  test first (TDD).
- 1 × B104 bind to 0.0.0.0 in `dte/docker/entrypoint.py:46`: intended inside a
  container. `# nosec B104` with that reason.

### 6. pip-audit — job is broken, not failing

`uv run pip-audit` → "Failed to spawn": pip-audit isn't in the `dev` extra.
Run it via `uvx pip-audit` against the locked requirements
(`uv export --frozen | uvx pip-audit -r /dev/stdin --strict`), then fix what
it reports.

### 7. pnpm audit — high advisories in transitive deps

`brace-expansion` (needs ≥1.1.18 / ≥2.1.4) and `js-yaml` (≥4.3.0). Bump the
parents; if they don't have a fixed release yet, add `pnpm.overrides` in
`frontend/package.json`.

## Tasks

Each task is its own worktree and branch, merged `--no-ff` into `dte-airflow`,
then pushed to `flowexperts/dte-airflow` main.

1. `feature/ci-security-config`: gitleaks ignore (4), pip-audit invocation
   (6), weekly schedule for the two audits, B104 nosec. Security goes green
   apart from bandit B608 and the audits.
2. `feature/ci-backend-lint`: ruff (1), then run the backend tests and fix
   what they surface (3).
3. `feature/ci-bandit-sql`: B608 review (5), with tests for any real
   injection path.
4. `feature/ci-frontend-lint`: eslint (2), then frontend tests, typecheck and
   format (3).
5. `feature/ci-deps`: pnpm overrides and bumps (7), plus pip-audit fixes.

Order: 1 → 2 → 4 → 3 → 5. 1 and 2 are small and turn most of the red
green.

## Files

- new: `.gitleaksignore`
- changed: `.github/workflows/security.yml`, `frontend/package.json`,
  `frontend/pnpm-lock.yaml`, ~40 files under `backend/dte` (mostly
  `ruff --fix`), ~10 under `frontend/src/components`
- deleted: none
