# Plan 072 — Model keys come from Airflow connections

Supersedes the store-based design in plan 052 (written before DTE became an
Airflow app). Branch: `feature/072-model-airflow-connections`.

## Problem

`structure` (claude/openai) and automap's LLM pass read `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` from the environment, wired through compose to every Airflow
container — plus a plaintext `params.api_key` on the step. Every other
credential in DTE is an Airflow Connection. Env keys are one-per-deployment,
rotate only by redeploy, and are invisible in the Airflow UI.

## Architecture change

Use the official providers' hooks; DTE keeps no key handling of its own.

| DTE provider | Airflow provider | conn type | default conn id |
|---|---|---|---|
| `claude` | `apache-airflow-providers-anthropic` | `anthropic` | `anthropic_default` |
| `openai` | `apache-airflow-providers-openai` | `openai` | `openai_default` |

The hooks own client construction (password = API key, host = base_url,
Bedrock/Vertex/workload identity via extras).

- `StructureStep.connection_id: str | None` — `None` means the default conn id.
- `params.api_key` is rejected at validation: step params are plaintext JSONB.
- `_apply_structure` builds the client **once per step**; a missing
  connection is a `CompilerError` before any row runs.
- `GET /api/providers/structure` reports readiness from Airflow and lists the
  conn ids of each type for the step editor's picker.
- Env vars are removed from compose. `AIRFLOW_CONN_ANTHROPIC_DEFAULT` still
  works — it is an Airflow connection.

**Versions.** Airflow 3.3.2 constraints pin `common-compat==1.19.0`;
anthropic provider 1.2.0 needs `>=1.21`, so pin `>=1.1,<1.2`. It needs
`anthropic>=1.0`, so DTE's `[models]` pin moves from `<1.0` to `>=1.0,<2.0`
(`output_config` verified on 1.17). openai provider is pinned by constraints
(1.8.2).

## Tasks

- [ ] tests first: provider status, structure step validation + client
      injection, automap
- [ ] `dte/airflow/connections.py`: `model_client`, `model_connections`
- [ ] `StructureStep.connection_id` + reject `params.api_key`
- [ ] providers take an injected `client`
- [ ] compiler resolves the client once per step
- [ ] status route from Airflow
- [ ] automap via `model_client`
- [ ] sweep axes drop `params.api_key`
- [ ] frontend connection picker + regen types
- [ ] deps, Dockerfile, compose, `.env.example`, docs

## Files

Changed: `backend/dte/airflow/connections.py`, `backend/dte/models/pipeline.py`,
`backend/dte/providers/structure.py`, `backend/dte/compiler/ibis_compiler.py`,
`backend/dte/api/routes/providers.py`, `backend/dte/automap.py`,
`backend/dte/evals/sweep.py`, `backend/pyproject.toml`, `Dockerfile.airflow`,
`docker-compose.yml`, `.env.example`, `backend/CLAUDE.md`,
`frontend/src/components/builder/steps/editors.tsx`, `frontend/src/lib/api.ts`,
`frontend/src/lib/api-types.ts`, `scripts/demo/*`, tests.
Deleted: none.
