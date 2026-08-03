/**
 * Zod schemas for pipeline builder validation.
 *
 * These schemas mirror the submit-time checks that lived inline in
 * BuilderForm.validate() and are the single source of truth for both
 * field-level (on-blur) and form-level (on-submit) validation.
 */

import { z } from "zod";

/**
 * Pipeline id is opaque and server-generated (UUID). On create the client
 * sends an empty string and the backend fills it in; on edit the client
 * echoes the server's value back. We only require that if a value IS
 * present it's non-empty — the shape is not the frontend's concern.
 */
export const pipelineIdSchema = z.string();

/** Pipeline name: non-empty string. */
export const pipelineNameSchema = z
  .string()
  .min(1, "Pipeline name is required.");

/**
 * A single step in the pipeline.
 * Only the select and map/lookup steps carry field-level constraints.
 */
export const stepSchema = z
  .object({
    op: z.string(),
    mode: z.string().optional(),
    fields: z.array(z.unknown()).optional(),
    drop: z.array(z.unknown()).optional(),
    lookup_id: z.string().optional().nullable(),
  })
  .passthrough()
  .superRefine((step, ctx) => {
    if (
      step.op === "select" &&
      (!step.fields || step.fields.length === 0) &&
      (!step.drop || step.drop.length === 0)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "Select step needs at least one field to keep or drop. Pick one or remove the step.",
      });
    }
    if (step.op === "map" && step.mode === "lookup" && !step.lookup_id?.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Map lookup step needs a saved lookup table picked.",
      });
    }
  });

/** Top-level pipeline shape as validated by the builder form. */
export const pipelineFormSchema = z.object({
  id: pipelineIdSchema,
  name: pipelineNameSchema,
  sources: z
    .array(z.string())
    .min(1, "Add at least one source.")
    .refine(
      (sources) => sources.every((s) => Boolean(s)),
      "Every source slot needs a saved source picked.",
    )
    .refine(
      (sources) => new Set(sources).size === sources.length,
      "Each source can only be added to a pipeline once.",
    ),
  output_id: z.string().min(1, "Pick or create a destination."),
  steps: z.array(stepSchema).optional(),
});

export type PipelineFormValues = z.infer<typeof pipelineFormSchema>;

/**
 * Validate a single field by key and return an error string or null.
 * Used for on-blur inline validation.
 */
export function validateField(
  field: "id" | "name" | "sources" | "output_id",
  value: unknown,
): string | null {
  const schema: z.ZodType<unknown> = {
    id: pipelineIdSchema as z.ZodType<unknown>,
    name: pipelineNameSchema as z.ZodType<unknown>,
    sources: pipelineFormSchema.shape.sources as z.ZodType<unknown>,
    output_id: pipelineFormSchema.shape.output_id as z.ZodType<unknown>,
  }[field];

  const result = schema.safeParse(value);
  if (result.success) return null;
  return result.error.issues[0]?.message ?? "Invalid value.";
}

/**
 * Validate the entire form and return a flat error map.
 * Returns an empty object when the form is valid.
 */
export function validatePipelineForm(values: {
  id: string;
  name: string;
  sources: string[];
  output_id: string;
  steps?: unknown[];
}): Record<string, string> {
  const result = pipelineFormSchema.safeParse(values);
  if (result.success) return {};

  const errors: Record<string, string> = {};
  for (const issue of result.error.issues) {
    const key = issue.path[0];
    if (key !== undefined && !errors[String(key)]) {
      errors[String(key)] = issue.message;
    }
  }
  return errors;
}
