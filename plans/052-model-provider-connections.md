# Plan 052 — Model providers as first-class Connections

> Depends on plan 050 Phase 1 (the `structure` step). Slots in as a P1 task
> ahead of the document inspector: every model call made before this lands is
> made with a credential that has no home.

## Problem

The `structure` step needs an Anthropic or OpenAI API key. Today it has two
ways to get one, and both are wrong.

**1. `params.api_key` on the step.** `ClaudeStructureProvider._call` reads
`params.get("api_key")`. Step params are stored in `pipelines.steps`, a plain
JSONB column. So a key set this way is:

- unencrypted at rest, while every other credential in the product goes
  through `EncryptedJSON`;
- rendered in the builder, and in whatever a pipeline export produces;
- copied into every pipeline revision, so rotation does not retract it;
- invisible to any audit — nothing knows a secret is in there.

This is the only place in DTE where a secret can be written to the database in
plaintext. It should not merely be discouraged; it should be rejected.

**2. `ANTHROPIC_API_KEY` in the environment.** Safe at rest, and correct for a
single-tenant dev box. It does not survive contact with the product's own
model:

- **One key per deployment.** Connections are tenant-scoped with RLS. An env
  var is not. Two tenants on one deployment share a key, share a rate limit,
  and share a bill.
- **No per-pipeline separation.** A team cannot bill extraction to one project
  and evals to another, which plan 051's sweeps make an immediate need — a
  50-cell sweep is exactly the thing you want on its own key.
- **Rotation is a redeploy**, and it is all-or-nothing.
- **No connectivity test.** Every other integration has
  `POST /api/connections/{id}/test`. A wrong model key is discovered one row
  into a 10k-document run.
- **Invisible in the UI.** The user cannot see whether a key is configured,
  which is why "why did my structure step fail" is currently unanswerable
  without shell access to the container.

Connections exist precisely for this. Model providers should not be the
exception.

## Architecture

### The novel part: a connection referenced by a *step*

Every existing connection is referenced by a Source or a Destination — the
"where" tier. A model provider has no "where". It attaches to a **step**, and
that is the first time a connection is referenced from inside
`pipelines.steps`.

That single fact drives most of the work below, and it breaks one existing
invariant (see "Sharp edges").

```
Connection (anthropic | openai — credentials, encrypted)
    ↑ connection_id
StructureStep (inside Pipeline.steps JSONB)
```

### Credential spec

`ConnectionType` gains `"anthropic"` and `"openai"`. Neither is a dlt
integration, so `_DLT_CRED_CLASS` has no class to delegate to. This is already
a solved shape in the codebase — `local_fs` maps to `None`, and `_GcsHmacSpec`
/ `_AzureSpec` are hand-written specs. Add `_ModelKeySpec`:

```python
@dataclass
class _ModelKeySpec:
    api_key: str
    base_url: str | None = None     # Bedrock / Vertex / a gateway / a proxy
```

`base_url` is not speculative: it is how a customer points at Bedrock or an
internal gateway, and adding it later means a credential migration.

**Validation on save**: non-empty `api_key`. Do **not** validate the prefix
(`sk-ant-`) — that is a format that will change and a rule that will produce
false rejections. Connectivity is what `test` is for.

### Resolution at compile time

`StructureStep` gains `connection_id: str | None`. The compiler's
`_apply_structure` resolves it through `ConnectionStore`, decrypts, and passes
the key into the provider — the same path `_load_documents` already uses for
storage credentials. The provider signature does not change; `params` gains a
resolved `api_key` that never touches the database.

**Fallback policy** (a real decision, stated rather than defaulted): if
`connection_id` is unset, fall back to the environment variable, but log at
WARNING naming the pipeline and step. Rationale — a hard requirement breaks
every pipeline built during plan 050 development and makes local dev need a
database round-trip for a key already sitting in the shell. The warning is
what keeps the fallback from becoming the norm. `DTE_REQUIRE_MODEL_CONNECTION=1`
turns it into an error for deployments that want the guarantee.

### Rejecting the plaintext path

`StructureStep` grows a validator rejecting `api_key` in `params`, mirroring
the existing `_REJECTED_PARAMS` check for `temperature`:

```python
if "api_key" in self.params:
    raise ValueError(
        "api_key cannot be set in step params — step params are stored "
        "unencrypted. Create an anthropic/openai Connection and set "
        "connection_id instead."
    )
```

This is a breaking change for any pipeline already using it. Given the feature
has never been merged to `main`, the blast radius is zero today and grows
every week it waits — which is the argument for doing it now rather than
after the inspector.

### Connectivity probe

`GET /v1/models` on both providers: authenticated, cheap, no tokens billed,
and it fails distinctly on a bad key (401) versus a network problem. Do **not**
probe with a 1-token `messages.create` — it bills, it can be rate-limited, and
on a model the key lacks access to it fails in a way that looks like a bad
key.

## Sharp edges

**1. The delete guard does not see step references.** `delete_connection`
(`dte/api/routes/connections.py:182`) scans sources and destinations only.
A connection referenced solely by a structure step would be **deletable**,
silently breaking every pipeline using it — and the 409 body's
`referenced_by: {sources, destinations}` shape has no field for it. Both the
single and bulk delete paths need a pipeline-steps scan and a third key,
`pipelines`. This is the single most likely thing to be missed; it gets its own
test.

**2. Cross-container env.** Triggered runs execute on the `worker`, previews on
`backend`. A key wired to only one produces the maddening "Preview works,
Trigger fails" split. Compose passes both; any deployment manifest must too.

**3. Key in the compiled expression.** `_apply_structure` closes over the
resolved key inside the enrichment mapper. It must not land in
`structure_meta`, run logs, or an error message — the `except Exception` in
`_ModelStructureProvider.structure` stringifies the exception, and SDK errors
can include request context. Scrub before persisting.

**4. `base_url` widens SSRF surface.** A user-supplied URL that the backend
then calls is a request-forgery primitive. Restrict to https, and reject
link-local and private ranges unless `DTE_ALLOW_PRIVATE_MODEL_URLS=1`.

## Task list

Worktrees per CLAUDE.md: `git worktree add ./worktrees/<name> -b feature/<name>`.

### Phase 1 — the connection type (`feature/052-model-connections`)
1. `ConnectionType += "anthropic" | "openai"`; `_ModelKeySpec` +
   `_DLT_CRED_CLASS` entries. Unit tests first: save/round-trip through
   `EncryptedJSON`, empty key rejected, no prefix validation.
2. Probe in `dte/sources/connection_test.py` — `GET /v1/models`, distinguishing
   401 from a transport error. Test with a mocked transport; no live calls.
3. Delete-guard: scan `pipelines.steps` for `connection_id`, add `pipelines`
   to the 409 `referenced_by` body, in **both** the single and bulk paths.
   A test that deletes a step-referenced connection and expects 409.

### Phase 2 — wiring it into the step (`feature/052-structure-connection`)
4. `StructureStep.connection_id`; validator rejecting `params.api_key`.
5. `_apply_structure` resolves and injects; env fallback with a WARNING;
   `DTE_REQUIRE_MODEL_CONNECTION` to harden.
6. Scrub credentials from error paths and `structure_meta`. Test asserting a
   provider exception carrying the key does not reach the run row.

### Phase 3 — surfaces (`feature/052-model-connection-ui`)
7. `pnpm gen:types`; the two kinds in the connections UI (label, form, test
   button — the existing `ConnectionPicker` handles the rest).
8. `ConnectionPicker` on `StructureEditor`, filtered to the provider's type,
   with an inline "+ New connection" mirroring `SourcesPanel`.
9. Remove the "Model" free-text hint about env keys; point at the connection.

### Phase 4 — cost attribution (`feature/052-model-usage`) — optional
10. Persist `input_tokens` / `output_tokens` per run (the provider already
    returns them and `StructureResult` already carries them; nothing reads
    them). This is what makes plan 051's sweep cost pre-flight real rather
    than estimated.

## Files touched

**New**: `backend/tests/unit/test_model_connections.py`,
`frontend/src/components/builder/connections/ModelConnectionEditor.tsx`.

**Modified**: `backend/dte/models/pipeline.py` (`ConnectionType`,
`_ModelKeySpec`, `_DLT_CRED_CLASS`, `StructureStep`),
`backend/dte/compiler/ibis_compiler.py` (`_apply_structure`),
`backend/dte/providers/structure.py` (scrubbing),
`backend/dte/sources/connection_test.py`,
`backend/dte/api/routes/connections.py` (delete guard, both paths),
`frontend/src/components/builder/steps/editors.tsx`,
`frontend/src/lib/api-types.ts`, `docker-compose.yml`, `CLAUDE.md`.

**Deleted**: none. `params.api_key` support is removed by validator, not by
deleting the read — `params` stays an open dict.

## Verification

```bash
cd backend && uv run pytest tests/unit/test_model_connections.py -x
cd backend && uv run pytest
cd backend && uv run pytest tests/scenarios -m scenario -k structure -v
```

Assertions that must exist — these are the failures this plan is for:
- A connection referenced only by a structure step returns **409** on delete,
  with the id listed under `referenced_by.pipelines`.
- `params: {"api_key": "..."}` is rejected at save with 422.
- A provider exception whose message contains the key does not put the key in
  `runs.error`.
- Saved credentials round-trip through `EncryptedJSON` and are masked by
  `GET /api/connections` (revealed only under `?reveal=true`).
- Two connections of the same type on one pipeline resolve independently — the
  test that catches a module-level client cache.

End-to-end: create an `anthropic` connection → **Test** returns ok → build a
documents → extract → structure pipeline referencing it → Preview succeeds →
Trigger succeeds (proving the worker path) → revoke the key upstream →
**Test** now fails with a 401-distinct message rather than a timeout.

## Not doing

- A model gateway, prompt caching, or router. `base_url` is the seam; a
  proxy is someone else's product.
- Per-key budget caps. Needs the usage persistence in task 10 first, and
  belongs with plan 051's cost pre-flight rather than here.
- Bedrock/Vertex first-class auth (SigV4, service accounts). `base_url` plus
  an API key covers the gateway case; native cloud auth is its own plan.
