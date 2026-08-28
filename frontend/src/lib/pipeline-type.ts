/**
 * The `/pipelines?type=` filter, shared by the list page and the sidebar.
 *
 * Kept in one place because the two used to disagree: the sidebar only ever
 * linked to `transform` and `quality`, and the page only recognised those
 * two. An eval pipeline could be created in the builder and then reached
 * from nowhere — the list that would have shown it was behind a `?type=`
 * neither link produced.
 */

export type PipelineTypeFilter = "transform" | "quality" | "eval" | "viz";

const KNOWN: readonly PipelineTypeFilter[] = ["transform", "quality", "eval", "viz"];

/**
 * Every type a pipeline can be, in nav order. Adding a `pipeline_type` to
 * the builder without adding it here leaves those pipelines unreachable.
 */
export const PIPELINE_TYPE_TABS: ReadonlyArray<{
  type: PipelineTypeFilter;
  label: string;
}> = [
  { type: "transform", label: "Transform" },
  { type: "quality", label: "Quality Check" },
  { type: "eval", label: "Eval" },
  { type: "viz", label: "Visualize" },
];

/**
 * `null` means "no filter — show everything". An unrecognised value returns
 * `null` rather than a default: silently substituting `transform` would hide
 * pipelines under a heading claiming to list them.
 */
export function parsePipelineType(raw: string | undefined): PipelineTypeFilter | null {
  return KNOWN.includes(raw as PipelineTypeFilter) ? (raw as PipelineTypeFilter) : null;
}

/**
 * The badge on a pipeline row. Defaults to `transform` for a pipeline with
 * no type, which is the historical shape — but an *unknown* type shows
 * itself rather than being flattened into "transform". A row that lies about
 * what it is costs more than an unfamiliar word.
 */
export function pipelineTypeLabel(type: string | null | undefined): string {
  return type ?? "transform";
}

export function pipelineListCopy(type: PipelineTypeFilter | null): {
  title: string;
  lede: string;
} {
  switch (type) {
    case "quality":
      return {
        title: "Quality pipelines",
        lede: "Data quality checks. Each run asserts conditions and reports pass/fail results.",
      };
    case "eval":
      return {
        title: "Eval pipelines",
        lede: "Extraction configs scored against a labeled corpus. They write no output — a run produces a score. Compare them on an eval set's leaderboard.",
      };
    case "viz":
      return {
        title: "Visualize pipelines",
        lede: "Pipelines that feed dashboard tiles. They write no output — a chart reads their rows directly. Add one to a dashboard to see it drawn.",
      };
    case "transform":
      return {
        title: "Transform pipelines",
        lede: "Batch data transformations. Click a row to open its builder or run history.",
      };
    default:
      return {
        title: "Pipelines",
        lede: "Batch data transformations. Click a row to open its builder or run history.",
      };
  }
}
