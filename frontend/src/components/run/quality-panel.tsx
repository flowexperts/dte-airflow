"use client";

import { useState, type ReactNode } from "react";
import { Panel, PanelHead, Pill } from "@/components/ui";
import type { QualityCheckResult } from "@/lib/api";
import { checkTone, parseViolations, toneVar } from "./helpers";

function statusLabel(r: QualityCheckResult): string {
  if (r.passed) return "Passed";
  return r.severity === "warn" ? "Warning" : "Failed";
}

export function QualityCheckRow({
  result,
  totalRows,
  action,
}: {
  result: QualityCheckResult;
  /** Denominator for the violation bar. Null when the run wrote nothing to
   *  measure against (quality pipelines) — the bar is dropped rather than
   *  invented. */
  totalRows: number | null;
  /** Trailing affordance, e.g. a link back to the check that failed. */
  action?: ReactNode;
}) {
  const tone = checkTone(result);
  const violations = result.passed ? null : parseViolations(result.detail);
  const pct =
    violations !== null && totalRows && totalRows > 0
      ? Math.min(100, (violations / totalRows) * 100)
      : null;

  return (
    <div className="grid grid-cols-[3px_1fr] border-b border-border last:border-b-0">
      <span style={{ background: toneVar[tone] }} />
      <div className="px-4 py-3">
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className="text-[13.5px] text-text font-medium">
            {result.label ?? result.contract_type}
          </span>
          <span className="font-mono text-[11px] text-subtle">
            {result.contract_id.slice(0, 8)}
          </span>
          <Pill status={result.passed ? "ok" : result.severity === "warn" ? "warn" : "failed"}>
            {statusLabel(result)}
          </Pill>
          {violations !== null && (
            <span
              className="ml-auto font-mono text-[11.5px] tabular-nums"
              style={{ color: toneVar[tone] }}
            >
              {violations.toLocaleString()} violating
            </span>
          )}
        </div>
        <div className="flex items-baseline gap-3">
          <div className="text-[12.5px] text-muted mt-1 min-w-0">
            {result.detail ?? (result.passed ? "All rows passed" : "—")}
          </div>
          {action && <span className="ml-auto">{action}</span>}
        </div>
        {pct !== null && (
          <div className="flex items-center gap-2.5 mt-2.5">
            <div className="flex-1 max-w-[320px] h-1.5 rounded-full bg-surface-2 overflow-hidden">
              <i
                className="block h-full"
                style={{ width: `${pct}%`, background: toneVar[tone] }}
              />
            </div>
            <span
              className="font-mono text-[11.5px] tabular-nums"
              style={{ color: toneVar[tone] }}
            >
              {pct.toFixed(1)}% of rows
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/** Primary presentation — used when checks *are* the run (quality pipelines). */
export function QualityPanel({
  results,
  totalRows,
  failedCount,
  actionFor,
}: {
  results: QualityCheckResult[];
  totalRows: number | null;
  failedCount: number;
  /** Per-result trailing affordance. Client-only — never pass this from a
   *  server component. */
  actionFor?: (r: QualityCheckResult) => ReactNode;
}) {
  return (
    <Panel>
      <PanelHead
        label="Quality checks"
        count={
          <>
            {results.length} check{results.length === 1 ? "" : "s"}
            {failedCount > 0 && (
              <span className="text-subtle"> · {failedCount} failed</span>
            )}
          </>
        }
      />
      {results.map((r) => (
        <QualityCheckRow
          key={r.contract_id}
          result={r}
          totalRows={totalRows}
          action={actionFor?.(r)}
        />
      ))}
    </Panel>
  );
}

/** Secondary presentation — used when checks are an assertion *about* the run
 *  (transform pipelines). Collapsed to one line when everything passed; opens
 *  itself when something didn't. */
export function QualityStrip({
  results,
  totalRows,
  failedCount,
  actionFor,
}: {
  results: QualityCheckResult[];
  totalRows: number | null;
  failedCount: number;
  /** Per-result trailing affordance. Client-only — never pass this from a
   *  server component. */
  actionFor?: (r: QualityCheckResult) => ReactNode;
}) {
  const [open, setOpen] = useState(failedCount > 0);

  return (
    <Panel>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 hover:bg-hover transition-colors text-left"
      >
        <span className="flex items-center gap-2">
          <span
            className={`text-[9px] text-muted inline-block transition-transform ${open ? "rotate-90" : ""}`}
          >
            ▶
          </span>
          <span className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
            Quality checks
          </span>
        </span>
        <span className="text-xs text-text">
          {results.length - failedCount}/{results.length} passed
        </span>
      </button>
      {open && (
        <div className="border-t border-border">
          {results.map((r) => (
            <QualityCheckRow
              key={r.contract_id}
              result={r}
              totalRows={totalRows}
              action={actionFor?.(r)}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}
