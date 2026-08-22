import type { Pipeline } from "./api";

/**
 * The eval pipelines that can legitimately be scored against one eval set.
 *
 * Two conditions, and the second is the one that used to be missing:
 *
 *  1. It is an eval pipeline (a transform pipeline writes output and has
 *     nothing to score).
 *  2. It reads the source the set's labels describe. Labels join to
 *     extracted rows by `doc_key` — the sha256 of the document — so a
 *     pipeline pointed at different documents produces hashes that match no
 *     label. The run completes, scores zero, and looks like a broken
 *     extractor rather than a mismatched corpus.
 *
 * Presence, not exclusivity: a pipeline may read other sources alongside the
 * corpus and still be scoring the right documents.
 *
 * The API enforces the same rule at trigger. Filtering here means the
 * rejection never has to happen — but the API is the guarantee, since a
 * sweep or a schedule can start a run without passing through this list.
 */
export function eligibleEvalPipelines(
  pipelines: Pipeline[],
  sourceId: string | undefined,
): Pipeline[] {
  // No corpus known — offer nothing rather than everything. An empty list is
  // a question someone can answer; a full list is a trap.
  if (!sourceId) return [];
  return pipelines.filter(
    (p) =>
      (p as { pipeline_type?: string }).pipeline_type === "eval" &&
      // `.includes` on an array of objects never matches a bare string — the
      // same fail-open bug as the pre-056 validation.ts guard.
      (p.sources ?? []).some((r) => r.source_id === sourceId),
  );
}
