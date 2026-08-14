/**
 * Validation and payload shaping for the new-eval-set form.
 *
 * Pure, so it can be tested without mounting React — the same split the
 * pipeline builder uses (`validation.ts`).
 *
 * An eval set is a contract between two things created separately: the
 * corpus and the pipeline that will be scored against it. The join is by
 * **field name**, so a typo here is not a validation error later — it is a
 * permanent zero on that field, which reads as a broken extractor. Most of
 * the rules below exist to catch that class of mistake while the user is
 * still looking at the form.
 */

/**
 * The comparator types offered in the UI.
 *
 * The backend's `COMPARATOR_TYPES` is wider — it also accepts the aliases
 * (`int`, `float`, `str`, `timestamp`, `set`, `boolean`) and `llm_judge`.
 * The aliases are omitted because two dropdown entries that do the same
 * thing invite the reader to believe they differ.
 *
 * `llm_judge` is omitted deliberately: it costs money on every comparison,
 * is non-deterministic, and a judge sharing a model family with the
 * extractor will flatter it. It should be a considered choice, not
 * something landed on while scrolling. Declare it via the API for now.
 */
export const FIELD_TYPES = [
  "string",
  "numeric",
  "date",
  "enum",
  "list",
] as const;

export type FieldType = (typeof FIELD_TYPES)[number];

export interface FieldDraft {
  name: string;
  type: string;
  description?: string;
  /** Relative tolerance, numeric fields only. Kept as a string: this is
   *  form state, and parsing mid-typing would fight the user. */
  rel_tol?: string;
}

export interface EvalSetDraft {
  id: string;
  name: string;
  source_id: string;
  fields: FieldDraft[];
}

export interface EvalSetPayload {
  id?: string;
  name: string;
  source_id: string;
  field_specs: Array<{
    name: string;
    type: string;
    description?: string;
    comparator?: Record<string, number>;
  }>;
}

/** Ids reach the UI as `/eval-sets/{id}` and every API path built from it. */
const ID_RE = /^[A-Za-z0-9_-]+$/;

export function validateEvalSetForm(draft: EvalSetDraft): Record<string, string> {
  const errors: Record<string, string> = {};

  // Blank means server-generated, which is a supported path — only a
  // non-empty id has to be well formed.
  if (draft.id.trim() && !ID_RE.test(draft.id.trim())) {
    errors.id = "Use letters, numbers, dashes and underscores only.";
  }

  if (!draft.name.trim()) {
    errors.name = "Give the eval set a name.";
  }

  if (!draft.source_id.trim()) {
    errors.source_id = "Pick the documents source holding the corpus.";
  }

  const names = draft.fields.map((f) => f.name.trim());
  if (draft.fields.length === 0) {
    errors.fields = "Add at least one field — these are what get scored.";
  } else if (names.some((n) => !n)) {
    errors.fields = "Every field needs a name.";
  } else {
    const dupe = names.find((n, i) => names.indexOf(n) !== i);
    if (dupe) {
      // Two specs under one name means one of them is silently unscored.
      errors.fields = `Duplicate field '${dupe}' — each field is scored once.`;
    }
  }

  return errors;
}

export function toEvalSetPayload(draft: EvalSetDraft): EvalSetPayload {
  const body: EvalSetPayload = {
    name: draft.name.trim(),
    source_id: draft.source_id.trim(),
    field_specs: draft.fields.map((f) => {
      const spec: EvalSetPayload["field_specs"][number] = {
        name: f.name.trim(),
        type: f.type,
      };
      const desc = f.description?.trim();
      if (desc) spec.description = desc;

      // A tolerance only means something to the numeric comparator. Sending
      // it on a string field would imply the scorer honours it.
      const isNumeric = f.type === "numeric";
      const tol = f.rel_tol?.trim();
      if (isNumeric && tol) {
        const parsed = Number(tol);
        if (Number.isFinite(parsed)) spec.comparator = { rel_tol: parsed };
      }
      return spec;
    }),
  };

  // Omit rather than send "": a blank primary key saves as a row that cannot
  // be referenced. The backend strips it too, but not sending it is clearer.
  const id = draft.id.trim();
  if (id) body.id = id;

  return body;
}
