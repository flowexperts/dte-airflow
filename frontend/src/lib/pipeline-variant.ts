/**
 * Sweep variants, and where Compare should point when you are looking at one.
 *
 * A sweep cell becomes a real pipeline named `<root>__<digest12>` —
 * deliberately, so a winner can be promoted and each run has something to
 * point at. But variants also appear in Pipelines → Eval carrying their own
 * Compare button, and comparing one used to nest it under itself:
 *
 *     demo_eval_strict__27fb9c1d2679__27fb9c1d2679__37f7b8bbec71
 *
 * The unreadable id was the visible half. The real harm was that each sweep
 * varied a setting a previous cell had already pinned, so people compared
 * against a config they never chose.
 *
 * Mirrors `dte/evals/sweep.py:root_pipeline_id` — the backend decides where
 * cells are filed, this decides where the button sends you, and the two
 * must agree.
 */

/** Exactly what `variant_id` appends: 12 lowercase hex characters. */
const VARIANT_SUFFIX = /^[0-9a-f]{12}$/;

/** The config someone authored, given any variant of it. */
export function rootPipelineId(pipelineId: string): string {
  const parts = pipelineId.split("__");
  // Narrow on purpose: an id ending `__2024` or `__abc` is somebody's own
  // naming convention, and stripping it would point Compare at a pipeline
  // that does not exist.
  while (parts.length > 1 && VARIANT_SUFFIX.test(parts[parts.length - 1]!)) {
    parts.pop();
  }
  return parts.join("__");
}

/**
 * Whether this pipeline is a sweep cell rather than something authored.
 *
 * `__eval` twins are not variants — the twin is the thing you compare
 * *from*, and treating it as a cell would send Compare to the transform
 * pipeline, which the corpus-match rule then refuses.
 */
export function isSweepVariant(pipelineId: string): boolean {
  return rootPipelineId(pipelineId) !== pipelineId;
}
