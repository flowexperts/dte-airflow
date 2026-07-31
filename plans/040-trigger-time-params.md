# Typed pipeline inputs (trigger-time params) and system variables

## Problem

Pipelines run on a schedule (hourly, daily) but filter and map expressions are static strings baked into the pipeline spec. There is no way to express "ingest records created since yesterday" without editing the pipeline each time. Orchestrators (cron, Airflow) already know the time window — they just have no way to pass it in.

Ad-hoc `{{params.foo}}` placeholders (v1 of this plan) worked but were untyped and un-declared: the pipeline author scattered names in SQL and the trigger form was a free-form key/value editor. Nothing bound the two ends together.

## Scope

**Pipeline inputs are first-class:** declared on the pipeline, typed, referenced from filter/map editors via a chip picker, and rendered as typed inputs on the trigger form.

Two independently-useful features, mechanically identical at the interpolation layer:

1. **Typed pipeline params** — declared on the pipeline as `[{name, type, required, default?, description?}]`. Filter/map expressions reference them via `{{params.<name>}}`. The trigger endpoint validates the caller's values against the declaration.
2. **System variables** — built-in names resolved at run time: `{{now}}`, `{{today}}`, `{{yesterday}}`, `{{start_of_week}}`, `{{start_of_month}}`. No caller input needed. Always available.

Both resolve through the same interpolation step before `compile_pipeline()`. Value substitution is string-based; SQL authors cast explicitly where needed (`'{{params.start_date}}'::date`). Type declarations exist for **input validation and UI generation**, not for changing how the value renders in SQL.

## Architecture

### Data model — `PipelineParam`

```python
ParamType = Literal["string", "int", "float", "date", "timestamp", "boolean"]

class PipelineParam(BaseModel):
    name: str                       # ^[a-zA-Z_][a-zA-Z0-9_]*$
    type: ParamType
    required: bool = True
    default: str | None = None      # stringified — coerced against `type` on save
    description: str | None = None
```

Added to `PipelineBase`:

```python
params: list[PipelineParam] = SMField(default_factory=list)
```

Table override on `Pipeline`: JSONB column with `server_default="'[]'::jsonb"`.

### Save-time validation

`PipelineBase._validate_param_refs()` (new model validator) scans every filter/map `expr` for `{{params.X}}` references. Any `X` not declared in `self.params` → `ValueError`, surfaced as 422 on POST/PUT. System vars are always valid.

Declared param names must be unique. Declared defaults must parse against their declared type (`_coerce_param_value` reused).

### Interpolation seam

`dte/compiler/interpolate.py`:

```python
def resolve_context(
    pipeline: Pipeline,
    user_values: dict[str, str] | None = None,
) -> dict:
    """Build the runtime context.

    - Validates `user_values` against `pipeline.params` (coerces per declared
      type, applies defaults, raises `ParamValidationError` on missing
      required or type mismatch).
    - Merges system vars.
    """

def interpolate_pipeline(pipeline: Pipeline, context: dict) -> Pipeline: ...
```

Coercion rules (all strings on the wire; native types only exist momentarily for validation):

| type | validated by | rendered back as |
| --- | --- | --- |
| `string` | passthrough | as-is |
| `int` | `int(v)` | `str(int(v))` |
| `float` | `float(v)` | `str(float(v))` |
| `boolean` | one of `true/false/1/0/yes/no` (case-insensitive) | `"true"` or `"false"` |
| `date` | `date.fromisoformat(v)` | ISO string |
| `timestamp` | `datetime.fromisoformat(v)` | ISO string |

Type mismatches raise `ParamValidationError` (subclass of `ValueError`), surfaced as 422 with a payload naming the offending param and expected type.

### Trigger endpoint

```json
POST /api/pipelines/{id}/trigger
Body: { "params": { "start_date": "2024-07-01" } }
```

`_execute_pipeline` resolves the context once at trigger time (freezes `now/today`), persists it on the run row, and reuses it inside `_run_body` so the resolved values match what the run record shows.

Run record gets a nullable `params: jsonb` column with the resolved context — inspectable after the fact.

### Preview / dry-run

`GET /api/pipelines/{id}/preview?params=<json>` and `POST /api/pipelines/dry-run?params=<json>` accept a JSON-encoded value dict, run it through the same validation, and interpolate before compiling. This lets the builder preview parameterised pipelines with sample values before saving.

Missing required params in preview show a friendly `error` string in the response (no 500).

### Compiler — no change

`compile_pipeline` receives an already-interpolated `Pipeline`. It stays unaware of variables.

## Data model — DB

```
pipelines
  + params  jsonb NOT NULL DEFAULT '[]'   -- list[PipelineParam]

runs
  + params  jsonb                         -- resolved {params: {…}, now, today, …}
```

One migration `019_run_and_pipeline_params.py` for both columns (idempotent `ADD COLUMN IF NOT EXISTS`).

## API surface

```
POST /api/pipelines                       validates param refs on save
PUT  /api/pipelines/{id}                  validates param refs on save
POST /api/pipelines/{id}/trigger
  body: TriggerRequest { params?: dict[str, str] }
GET  /api/pipelines/{id}/preview?limit&params=<json>
POST /api/pipelines/dry-run?limit&params=<json>
GET  /api/runs/{id}                       response includes params
```

Validation errors from param-refs, missing-required, or type-coerce return **422** with `{code, param, expected_type, got}` where applicable.

## Frontend

### Builder — Inputs panel

Under the Steps panel in `BuilderForm`, add an **Inputs** panel. Rows: `name / type dropdown / required toggle / default / description`. `+ Add input` button. Validation is inline (name pattern, duplicate name, default parses).

The `params` array rides on the Pipeline object and is submitted with POST/PUT unchanged.

### Filter editor — typed param picker

In the Advanced filter tab (`FilterEditor`), the "Available variables" hint becomes two rows:

- **System:** chips for `{{now}}` … `{{start_of_month}}` (always available).
- **Params:** chips for each declared param name (colored + typed suffix, e.g. `start_date · date`). Empty state: "No inputs declared. Add them in the Inputs panel."

Clicking a chip inserts `{{params.<name>}}` at the cursor. Same picker mounted on the ExpressionMap editor's expression textarea.

### Trigger modal — typed inputs

`TriggerModal` reads `pipeline.params`. For each declared param, render:

- **string** → text input
- **int / float** → number input
- **date** → `<input type="date">`
- **timestamp** → `<input type="datetime-local">`
- **boolean** → segmented `true / false`

Required params are marked with `*` and disable the Submit button until filled. Optional params show `(optional)` and inherit the declared default as placeholder.

If the pipeline has **zero declared params**, the modal is a single-confirm "Run now?" dialog.

### Run detail — resolved params display

On `runs/[id]/page.tsx`, if `run.params?.params` is non-empty, render a `Trigger params` panel with a KV grid of the caller-supplied values. System variables (`now`, `today`, …) are not shown (noise).

## Files touched

**Backend**
- `dte/models/pipeline.py` — `PipelineParam` model, `PipelineBase.params`, `Pipeline.params` sa_column, `_validate_param_refs`
- `dte/compiler/interpolate.py` — coercion, `ParamValidationError`, `resolve_context(pipeline, user_values)`
- `dte/api/routes/pipelines.py` — thread validated params, TriggerRequest, param error → 422
- `backend/alembic/versions/019_run_and_pipeline_params.py`
- `tests/unit/test_interpolate.py` — coercion, missing required, unknown var, ref validation
- `tests/scenarios/test_trigger_params.py` — declare param → trigger with typed value → filtered rows

**Frontend**
- `src/lib/api.ts` — `PipelineParam`, `Pipeline.params`, `triggerPipeline(id, params)`, `Run.params`
- `src/components/builder/inputs-panel.tsx` (new) — declares params
- `src/components/builder/BuilderForm.tsx` — mount InputsPanel, thread `params` through save
- `src/components/builder/steps/editors.tsx` — typed `VariablePickerHint`
- `src/components/trigger-modal.tsx` — typed inputs driven by declared params
- `src/components/trigger-button.tsx` — pass `params` schema
- `src/app/(app)/pipelines/[id]/page.tsx` — pass `pipeline.params` to TriggerButton
- `src/app/(app)/runs/[id]/page.tsx` — resolved params KV block

## Out of scope

- **Typed SQL emission** — values still substitute as bare strings; the SQL author writes casts. A `date` param renders as its ISO string; wrap in quotes + `::date` as usual. Emitting `DATE '…'` literals is a follow-up if we hit ergonomics complaints.
- **Secret-marked params** — no masking or vault integration; params land plaintext in `runs.params`.
- **Cross-pipeline default templates** — each pipeline declares its own params.
- Params on scheduled / recurring pipeline configs (plan 041's cursor work).

## Verification

1. Unit: `cd backend && uv run pytest tests/unit/test_interpolate.py -x`
2. Scenario: `cd backend && uv run pytest tests/scenarios/test_trigger_params.py -m scenario -x -v`
3. Manual:
   - Open the builder, declare a `min_amount` param (type `float`, required).
   - In a filter step, Advanced tab → click the `min_amount` chip → get `{{params.min_amount}}`.
   - Save → **Run now** → modal shows a numeric input; entering `not-a-number` is blocked client-side.
   - Trigger a valid value → run page shows the resolved value in the "Trigger params" panel.
   - Change the pipeline to reference `{{params.missing}}` without declaring it → save returns 422.
