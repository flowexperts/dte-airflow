import type { ReactNode } from "react";
import type { Pipeline, Run, Source, Destination } from "@/lib/api";
import { statusTone, toneVar, STATUS_LABEL } from "@/components/run/helpers";

/** "4m ago" / "3d ago". Absolute dates below a day are noise on a list. */
export function relativeTime(iso?: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export const isQualityPipeline = (p: Pipeline) => p.pipeline_type === "quality";
export const isEvalPipeline = (p: Pipeline) => p.pipeline_type === "eval";

/** Labels that read the same on detail, list, and run pages. */
export function pipelineShape(p: Pipeline): string {
  const sources = p.sources?.length ?? 0;
  const steps = p.steps?.length ?? 0;
  if (isQualityPipeline(p)) {
    const checks = (p.steps ?? []).filter(
      (s) => s.op === "check" || s.op === "profile",
    ).length;
    return `${sources} src · ${checks || steps} check${(checks || steps) === 1 ? "" : "s"}`;
  }
  if (isEvalPipeline(p)) {
    // Not "no output". An eval pipeline having no destination is the design,
    // but rendered in the transform shape it reads as an unfinished pipeline
    // someone forgot to point somewhere.
    const fields = (p.steps ?? []).find((s) => s.op === "structure");
    const n = (fields?.model as { fields?: unknown[] } | undefined)?.fields?.length ?? 0;
    return `${sources} src · ${n} field${n === 1 ? "" : "s"} scored`;
  }
  return `${sources} → ${steps} → ${p.output_id ? "output" : "no output"}`;
}

/**
 * One-line outcome for a finished run, shared by the list cell and the detail
 * header. Quality runs report checks; transform runs report rows.
 */
export function runOutcome(run: Run | undefined, quality: boolean): string {
  if (!run) return "never run";
  if (run.status === "running" || run.status === "pending") {
    return STATUS_LABEL[run.status];
  }
  if (quality) {
    const q = run.quality;
    if (!q) return STATUS_LABEL[run.status];
    const total = q.passed + q.failed + q.warned;
    const bad = q.failed + q.warned;
    return bad > 0 ? `${bad}/${total} failed` : `${total} passed`;
  }
  if (run.status === "completed" || run.status === "completed_with_warnings") {
    return `${(run.rows_written ?? 0).toLocaleString()} rows`;
  }
  return STATUS_LABEL[run.status];
}

/** Dot + text in the run's tone. Used wherever a run's health is summarised. */
export function RunTone({
  run,
  children,
}: {
  run: Run | undefined;
  children: ReactNode;
}) {
  const tone = statusTone(run?.status);
  const color = tone === "pending" ? "var(--subtle)" : toneVar[tone];
  const live = run?.status === "running";
  return (
    <span className="inline-flex items-center gap-1.5 min-w-0">
      <span
        className={`size-1.5 rounded-full shrink-0 ${live ? "animate-pulse-dot" : ""}`}
        style={{ background: color }}
      />
      <span className="truncate" style={{ color }}>
        {children}
      </span>
    </span>
  );
}

/** Five most recent outcomes as squares — health trend without a chart. */
export function RunSparkline({ runs }: { runs: Run[] }) {
  const recent = runs.slice(0, 5);
  if (recent.length === 0) {
    return <span className="font-mono text-[11px] text-subtle">no runs</span>;
  }
  return (
    <span className="inline-flex items-center gap-1" aria-hidden>
      {recent.map((r) => {
        const tone = statusTone(r.status);
        return (
          <span
            key={r.id}
            className="size-1.5 rounded-[1px]"
            style={{
              background: tone === "pending" ? "var(--border-2)" : toneVar[tone],
            }}
          />
        );
      })}
    </span>
  );
}

/* Config labels — the detail page needs a human path for a source or a
 * destination, and both bury it at a different key per kind. */

export function sourcePathLabel(s: Source): string {
  const cfg = (s.config as Record<string, unknown>) ?? {};
  return (
    (cfg.bucket_url as string) ??
    (cfg.connection_string as string) ??
    (cfg.connection_url as string) ??
    s.source_type
  );
}

export function destinationPathLabel(d: Destination): string {
  const c = d.config as Record<string, unknown>;
  return (
    (c.path as string) ??
    (c.bucket_url as string) ??
    (c.table as string) ??
    d.config.type
  );
}
