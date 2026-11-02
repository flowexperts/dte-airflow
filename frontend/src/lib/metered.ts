/** Helpers for metered warehouse sources (plan 093): which pipelines read
 *  one, how old a cached sample is, and which partition filters are missing. */
import useSWR from "swr";
import type { Connection, Source } from "./api";

/** Connection kinds that bill per query (backend `METERED`). */
const METERED_KINDS = new Set(["bigquery", "snowflake"]);

/** Whether any of `refs` reads a metered warehouse; `null` until both lists
 *  have loaded, so callers hold billable work rather than guess. */
export const readsMetered = (
  refs: Array<{ source_id: string }>,
  sources: Array<Pick<Source, "id" | "connection_id">> | undefined,
  connections: Array<{ id: string; connection_type: string }> | undefined,
): boolean | null => {
  if (!sources || !connections) return null;
  const kind = new Map(connections.map((c) => [c.id, c.connection_type]));
  const conn = new Map(sources.map((s) => [s.id, s.connection_id]));
  return refs.some((r) => METERED_KINDS.has(kind.get(conn.get(r.source_id) ?? "") ?? ""));
};

/** `readsMetered` over the shared SWR source and connection lists. */
export const useReadsMetered = (refs: Array<{ source_id: string }> | undefined): boolean | null => {
  const { data: sources } = useSWR<Source[]>("/api/sources");
  const { data: connections } = useSWR<Connection[]>("/api/connections");
  return readsMetered(refs ?? [], sources, connections);
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
