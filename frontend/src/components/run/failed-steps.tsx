"use client";

import Link from "next/link";
import { Panel, PanelHead } from "@/components/ui";
import { labelFor, type StepShape } from "@/components/builder/steps/types";
import { stepTitle } from "@/components/builder/steps/summary";
import type { Pipeline, RunEvent } from "@/lib/api";
import { toneVar } from "./helpers";

/**
 * Link straight into the step that caused a problem.
 *
 * The pipeline page opens and scrolls to `#step-N` on load, so this closes the
 * loop a failed run used to leave open: previously the run told you *what*
 * broke but not *where*, and finding it meant navigating back and counting
 * step indices by hand.
 */
export function stepHref(pipelineId: string, index: number): string {
  return `/pipelines/${encodeURIComponent(pipelineId)}#step-${index}`;
}

export function FixStepLink({
  pipelineId,
  index,
  label = "Fix step",
}: {
  pipelineId: string;
  index: number;
  label?: string;
}) {
  return (
    <Link
      href={stepHref(pipelineId, index)}
      className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent no-underline hover:text-accent-h shrink-0"
    >
      {label} →
    </Link>
  );
}

/**
 * Failed steps lifted out of the diagnostics timeline and given a route back
 * into the editor. Renders nothing when no step-level failure was recorded —
 * a compile error fails before any step runs, and the error panel covers that.
 */
export function FailedSteps({
  events,
  pipeline,
}: {
  events: RunEvent[];
  pipeline: Pipeline | undefined;
}) {
  const failed = events.filter((e) => e.status === "failed");
  if (failed.length === 0 || !pipeline) return null;
  const steps = (pipeline.steps ?? []) as StepShape[];

  return (
    <Panel>
      <PanelHead label="Where it broke" count={failed.length} />
      {failed.map((e, i) => {
        const idx = e.step_index ?? -1;
        const step = idx >= 0 ? steps[idx] : undefined;
        return (
          <div
            key={`${e.step_index}-${i}`}
            className="grid grid-cols-[3px_1fr] border-b border-border last:border-b-0"
          >
            <span style={{ background: toneVar.err }} />
            <div className="px-4 py-3">
              <div className="flex items-center gap-2.5 flex-wrap">
                <span className="font-mono text-[10px] font-bold tracking-[0.15em] uppercase text-accent px-1.5 py-0.5 rounded-sm bg-[color:var(--accent-tint)]">
                  {step ? labelFor(step) : e.op}
                </span>
                <span className="text-[13.5px] text-text font-medium">
                  {step ? stepTitle(step) : `step ${idx}`}
                </span>
                {idx >= 0 && (
                  <span className="ml-auto">
                    <FixStepLink pipelineId={pipeline.id} index={idx} />
                  </span>
                )}
              </div>
              {e.message && (
                <div className="text-[12.5px] text-muted mt-1 font-mono break-words">
                  {e.message}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </Panel>
  );
}
