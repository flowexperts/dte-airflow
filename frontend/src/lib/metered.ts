/** Helpers for metered warehouse sources (plan 093): what a query will scan,
 *  how old a cached sample is, and which partition filters are missing. */
import type { PipelineEstimate } from "./api";

/** "3.0 TiB" — binary units, matching how BigQuery prices (per TiB). */
export const formatBytes = (n: number): string => {
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return i === 0 ? `${n} B` : `${n.toFixed(1)} ${units[i]}`;
};

/** The one sentence shown before anything billable runs. */
export const estimateSentence = (e: PipelineEstimate, verb = "This run scans"): string => {
  const size = e.bytes != null ? `~${formatBytes(e.bytes)}` : "an unknown amount";
  const cost =
    e.est_cost_usd != null ? ` (~$${e.est_cost_usd.toFixed(2)}, on-demand estimate)` : "";
  const cap =
    e.exceeds_cap && e.max_bytes_billed != null
      ? ` That is above this connection's cap of ${formatBytes(e.max_bytes_billed)}, so ${e.engine} will refuse it.`
      : "";
  return `${verb} ${size}${cost} on ${e.engine}.${cap}`;
};

export const sampleAge = (iso: string, now = Date.now()): string => {
  const mins = Math.floor((now - Date.parse(iso)) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.floor(mins / 60)}h ago`;
  return `${Math.floor(mins / (60 * 24))}d ago`;
};

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Partition columns no filter step mentions. A word match on the filter's
 *  SQL, so it can't tell `ts > x` from `ts IS NOT NULL` — the warning is a
 *  nudge, the cap on the connection is the guard. */
export const unfilteredPartitions = (
  partitionColumns: string[],
  steps: Array<{ op?: string; expr?: unknown }>,
): string[] => {
  const exprs = steps.filter((s) => s.op === "filter").map((s) => String(s.expr ?? ""));
  return partitionColumns.filter((col) => {
    const re = new RegExp(`(^|[^A-Za-z0-9_])${escapeRe(col)}($|[^A-Za-z0-9_])`, "i");
    return !exprs.some((e) => re.test(e));
  });
};
