/**
 * The matrix a Compare run expands to.
 *
 * The sweep launcher this replaces took a free-text axis name and a
 * comma-separated value list. Two problems, both of which made the flow's
 * headline use case unreachable:
 *
 * 1. Its help text contradicted its own docstring — the docstring promised
 *    "providers × models × prompts", the form offered one axis. The API
 *    accepted a cartesian product the whole time.
 * 2. It offered `regex` as a provider value regardless of whether the
 *    structure step had per-field patterns. Without them the regex provider
 *    returns nothing on every row, so the cell scores ~0 — which reads as
 *    "regex is bad at this" rather than "regex was never configured".
 *
 * Pure functions so the arithmetic the user is about to spend against is
 * testable without rendering anything.
 */

/** Axis paths, which must match the keys `apply_cell` walks on the step. */
const PROVIDER_AXIS = "provider";
/** Not `model` — that key holds the field spec. */
const MODEL_AXIS = "params.model";
const INSTRUCTIONS_AXIS = "model.instructions";

/**
 * The providers and models offered as axes.
 *
 * Lifted out of the Compare wizard when the matrix moved onto the pipeline
 * (plan 055) so the builder panel and the cost estimator name models
 * identically — a model string that does not match `cost.PRICES` prices as
 * `unknown`, and one unpriced row nulls a whole run's cost by design.
 */
export const PROVIDERS = [
  { id: "claude", label: "Claude", hint: "strongest on messy layouts" },
  { id: "openai", label: "OpenAI", hint: "" },
  { id: "regex", label: "Regex", hint: "free, offline, exact provenance" },
];

export const MODELS: Record<string, { id: string; label: string }[]> = {
  claude: [
    { id: "claude-opus-5", label: "Opus 5" },
    { id: "claude-sonnet-5", label: "Sonnet 5" },
    { id: "claude-haiku-4-5", label: "Haiku 4.5" },
  ],
  openai: [
    { id: "gpt-5", label: "GPT-5" },
    { id: "gpt-5-mini", label: "GPT-5 mini" },
  ],
};

export type CompareDraft = {
  providers: string[];
  models: string[];
  instructions: string[];
};

export type FieldPattern = { name: string; pattern?: string | null };

export type RegexAvailability = { available: true } | { available: false; missing: string[] };

function clean(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values) {
    const value = raw.trim();
    // Blank slots are not configs. A duplicate is worse than useless: two
    // identical cells cost twice and then rank against each other, reading
    // as "the same config scored differently".
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

/** The `matrix` body for POST /eval-sets/{id}/sweep. */
export function buildMatrix(draft: CompareDraft): Record<string, string[]> {
  const matrix: Record<string, string[]> = {};
  const axes: [string, string[]][] = [
    [PROVIDER_AXIS, draft.providers],
    [MODEL_AXIS, draft.models],
    [INSTRUCTIONS_AXIS, draft.instructions],
  ];
  for (const [axis, values] of axes) {
    const cleaned = clean(values);
    // An axis present with an empty list is a 422 from `_expand_matrix`.
    // Omitting it is how "I only want to vary the provider" is expressed.
    if (cleaned.length > 0) matrix[axis] = cleaned;
  }
  return matrix;
}

/** Every axis this module knows how to render as chips. */
const OWNED_AXES = [PROVIDER_AXIS, MODEL_AXIS, INSTRUCTIONS_AXIS];

/**
 * The inverse of `buildMatrix` — a stored matrix back into chip state.
 *
 * This is what makes the matrix storable at all. Reopening a saved
 * comparison must restore the controls that produced it; without the
 * inverse the panel renders empty over a matrix that exists, and the next
 * save quietly discards every axis the user configured.
 *
 * Values are coerced to strings because JSONB round-trips numbers as
 * numbers (`params.max_tokens: [1000]`) while the chips are text.
 */
export function draftFromMatrix(
  matrix: Record<string, unknown[]> | null | undefined,
): CompareDraft {
  const axis = (name: string): string[] => (matrix?.[name] ?? []).map((v) => String(v));
  return {
    providers: axis(PROVIDER_AXIS),
    models: axis(MODEL_AXIS),
    instructions: axis(INSTRUCTIONS_AXIS),
  };
}

/**
 * Axes present in a stored matrix that this module has no control for.
 *
 * `params.max_tokens` and `params.api_key` are legal sweep axes with no
 * chips. Parsing them into the draft would misrepresent them, and dropping
 * them silently would delete a user's configuration on the next save — so
 * the panel reports them and leaves them untouched instead.
 */
export function unknownAxes(matrix: Record<string, unknown[]> | null | undefined): string[] {
  return Object.keys(matrix ?? {}).filter((k) => !OWNED_AXES.includes(k));
}

/** How many runs this draft launches — the number being spent against. */
export function cellCount(draft: CompareDraft): number {
  const lengths = Object.values(buildMatrix(draft)).map((v) => v.length);
  if (lengths.length === 0) return 0;
  return lengths.reduce((a, b) => a * b, 1);
}

/**
 * Whether `regex` can honestly be offered as a provider to compare.
 *
 * The regex provider errors out unless every declared field carries a
 * `pattern`. Offering it anyway produces a cell that runs, returns nulls,
 * and scores near zero — a result that looks like a measurement and is not
 * one. Naming the specific fields matters: "add patterns" is not
 * actionable, "vendor and due_date have none" is.
 */
export function regexAvailability(fields: FieldPattern[]): RegexAvailability {
  if (fields.length === 0) return { available: false, missing: [] };
  const missing = fields.filter((f) => !(f.pattern ?? "").trim()).map((f) => f.name);
  return missing.length === 0 ? { available: true } : { available: false, missing };
}
