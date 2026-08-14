"use client";

/**
 * Shared score rendering for the eval surfaces.
 *
 * Every rule here exists to stop the UI from asserting more than the numbers
 * support. A score of `null` is not zero, an interval that overlaps the
 * leader's is not second place, and a run scored against older labels is not
 * comparable to one scored against the current set. The backend already
 * refuses to rank those; these components make sure the rendering agrees.
 */

import type { FieldMetrics } from "@/lib/api";

const GREEN = "var(--green)";
const GOLD = "var(--gold)";
const RED = "var(--red)";

export function scoreTone(v: number | null | undefined): string {
  if (v == null) return "var(--subtle)";
  if (v >= 0.9) return GREEN;
  if (v >= 0.7) return GOLD;
  return RED;
}

/** `null` renders as an em dash, never as 0% — an undefined score must not
 *  look like a measured failure. */
export function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

export function ScoreBar({
  value,
  interval,
  width = 120,
}: {
  value: number | null;
  interval?: [number, number] | undefined;
  width?: number | undefined;
}) {
  if (value == null) {
    return <span className="font-mono text-[12px] text-subtle">—</span>;
  }
  const tone = scoreTone(value);
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className="relative inline-block h-[6px] rounded-full bg-hover overflow-hidden"
        style={{ width }}
      >
        {/* The confidence band is drawn *behind* the value so a wide band on a
            small n visibly swamps the point estimate — the honest picture. */}
        {interval && (
          <span
            className="absolute top-0 h-full opacity-30"
            style={{
              left: `${interval[0] * 100}%`,
              width: `${Math.max(0, (interval[1] - interval[0]) * 100)}%`,
              background: tone,
            }}
          />
        )}
        <span
          className="absolute top-0 h-full w-[2px]"
          style={{ left: `calc(${value * 100}% - 1px)`, background: tone }}
        />
      </span>
      <span className="font-mono text-[12px] tabular-nums" style={{ color: tone }}>
        {pct(value)}
      </span>
    </span>
  );
}

export function FieldChip({ metrics }: { metrics: FieldMetrics }) {
  const tone = scoreTone(metrics.f1);
  return (
    <span
      className="inline-flex items-baseline gap-1.5 px-2 py-0.5 rounded-[var(--radius)] border border-border"
      title={`tp ${metrics.tp} · fp ${metrics.fp} · fn ${metrics.fn} · tn ${metrics.tn}`}
    >
      <span className="text-[11.5px] text-muted">{metrics.name}</span>
      <span className="font-mono text-[11.5px] tabular-nums" style={{ color: tone }}>
        {pct(metrics.f1)}
      </span>
    </span>
  );
}

/** Sample size, stated next to every score rather than buried in a tooltip. */
export function SampleSize({ n }: { n: number }) {
  return (
    <span className="font-mono text-[11.5px] text-subtle tabular-nums">n={n}</span>
  );
}

export function StaleBadge() {
  return (
    <span
      className="text-[11px] px-1.5 py-0.5 rounded-[var(--radius)] border border-border text-subtle"
      title="Labels changed since this run. It is shown for history but excluded from ranking — comparing across a label edit measures the labels, not the extractor."
    >
      labels changed
    </span>
  );
}

export function TiedBadge() {
  return (
    <span
      className="text-[11px] px-1.5 py-0.5 rounded-[var(--radius)]"
      style={{ background: "var(--accent-tint)", color: "var(--accent)" }}
      title="Its confidence interval overlaps the leader's — the difference is not distinguishable from sampling noise."
    >
      tied
    </span>
  );
}
