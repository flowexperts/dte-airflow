import type { QualityCheckResult, Run, RunEvent, RunStatus } from "@/lib/api";

export function elapsedSeconds(started?: string | null, finished?: string | null): string {
  if (!started) return "—";
  const s = new Date(started).getTime();
  const e = finished ? new Date(finished).getTime() : Date.now();
  const ms = Math.max(0, e - s);
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function elapsedMs(started?: string | null, finished?: string | null): number | null {
  if (!started) return null;
  const s = new Date(started).getTime();
  const e = finished ? new Date(finished).getTime() : Date.now();
  return Math.max(0, e - s);
}

/** Quality `detail` strings all lead with the violating-row count
 *  ("9901385 value(s) out of range in column 'amount' (max=100)"). Pull it out
 *  so the check row can render a magnitude instead of burying it in prose. */
export function parseViolations(detail: string | null): number | null {
  if (!detail) return null;
  const m = /^(\d[\d,]*)\b/.exec(detail.trim());
  if (!m?.[1]) return null;
  const n = Number(m[1].replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}

export type Tone = "ok" | "warn" | "err";

export const toneVar: Record<Tone, string> = {
  ok: "var(--green)",
  warn: "var(--gold)",
  err: "var(--red)",
};

export function toneTint(tone: Tone, pct: number): string {
  return `color-mix(in srgb, ${toneVar[tone]} ${pct}%, transparent)`;
}

export function checkTone(result: QualityCheckResult): Tone {
  if (result.passed) return "ok";
  return result.severity === "warn" ? "warn" : "err";
}

export function statusTone(status: RunStatus | undefined): Tone | "pending" {
  switch (status) {
    case "completed":
      return "ok";
    case "completed_with_warnings":
      return "warn";
    case "failed":
    case "failed_quality":
      return "err";
    default:
      return "pending";
  }
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  completed_with_warnings: "Completed with warnings",
  failed: "Failed",
  failed_quality: "Quality checks failed",
};

export function qualityTally(
  results: QualityCheckResult[],
  fallback: Run["quality"],
): { total: number; failed: number; warned: number; passed: number } {
  if (results.length > 0) {
    const failed = results.filter((r) => !r.passed && r.severity === "fail").length;
    const warned = results.filter((r) => !r.passed && r.severity === "warn").length;
    return {
      total: results.length,
      failed,
      warned,
      passed: results.length - failed - warned,
    };
  }
  if (fallback) {
    const { passed, failed, warned } = fallback;
    return { total: passed + failed + warned, failed, warned, passed };
  }
  return { total: 0, failed: 0, warned: 0, passed: 0 };
}

/** Airflow's own pages for a run. Relative on purpose: Airflow's `<base href>`
 *  resolves them under any configured base_url. Use a plain `<a>`, not nav's
 *  `Link`, which would mount them under `/plugin/<page>`. */
export function airflowRunHref(dagId: string, runId: string): string {
  return `dags/${encodeURIComponent(dagId)}/runs/${encodeURIComponent(runId)}`;
}

/** The task instance page opens on its log. Every DTE DAG has one task, `run`
 *  (`dag_factory.py`). Airflow numbers log groups, it doesn't name them, so
 *  there's no anchor to a step's group. */
export function airflowTaskLogHref(dagId: string, runId: string): string {
  return `${airflowRunHref(dagId, runId)}/tasks/run`;
}

/** Steps and run phases (`step_index: null`) in the order they started. */
export function timeline(events: RunEvent[]): RunEvent[] {
  return [...events].sort((a, b) => (a.started_at ?? "").localeCompare(b.started_at ?? ""));
}

export function eventLabel(e: RunEvent): string {
  return e.step_index === null ? e.op : `${e.op} step ${e.step_index}`;
}
