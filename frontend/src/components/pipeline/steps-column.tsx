"use client";

import { useEffect, useRef, useState } from "react";
import { AddStep, Panel, PanelHead } from "@/components/ui";
import { StepEditor } from "@/components/builder/steps/editors";
import { StepIndexProvider, JoinOperandsProvider } from "@/components/builder/schema-context";
import { StepSummary, stepTitle } from "@/components/builder/steps/summary";
import {
  STEP_OPS,
  emptyStep,
  labelFor,
  type StepShape,
} from "@/components/builder/steps/types";
import { cn } from "@/lib/cn";
import type { SourceTableRef } from "@/lib/api";
import { AutoMapButton } from "@/components/builder/AutoMap";

/**
 * The ordered steps.
 *
 * Every step shows its editor — no click to expand. Reading a step and
 * changing it are the same act often enough that a disclosure just adds a
 * click, and a collapsed row hides the dropdowns that make the step
 * comprehensible in the first place.
 *
 * `openIndex` no longer gates the editor; it marks the step a deep link
 * (`#step-3` from a failed run) pointed at, so it can be scrolled to and
 * highlighted.
 */
export function StepsColumn({
  steps,
  onChange,
  pipelineType,
  openIndex,
  onOpenChange,
  readOnly,
  sources = [],
  outputId = "",
}: {
  steps: StepShape[];
  onChange: (steps: StepShape[]) => void;
  pipelineType: "transform" | "quality" | "eval";
  /** Deep-linked step, highlighted and scrolled to. */
  openIndex: number | null;
  onOpenChange: (i: number | null) => void;
  readOnly: boolean;
  /** Declared source aliases, offered as join operands alongside the
   *  output_id of any earlier join step. */
  sources?: SourceTableRef[];
  /** Destination whose table Auto-map matches against. */
  outputId?: string;
}) {
  const aliases = sources.map((r) => r.alias).filter(Boolean);
  const operandsAt = (i: number): string[] => {
    const priorJoinOutputs = steps
      .slice(0, i)
      .filter((s) => s.op === "join" && typeof s.output_id === "string" && s.output_id)
      .map((s) => s.output_id as string);
    return [...aliases, ...priorJoinOutputs];
  };
  const [addAt, setAddAt] = useState<number | null>(null);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const targetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (openIndex !== null) {
      targetRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [openIndex]);

  const openStepFromHash = () => {
    const m = /^#step-(\d+)$/.exec(window.location.hash);
    if (m?.[1]) onOpenChange(Number(m[1]));
  };

  useEffect(() => {
    openStepFromHash();
    window.addEventListener("hashchange", openStepFromHash);
    return () => window.removeEventListener("hashchange", openStepFromHash);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount + hash only
  }, []);

  const isQuality = pipelineType === "quality";
  const label = isQuality ? "Checks" : "Steps";

  const ops = STEP_OPS.filter((o) => {
    if (isQuality) {
      return o.category === "quality" || ["filter", "rename", "select", "join"].includes(o.op);
    }
    // An eval pipeline's job is to produce the fields being scored, so it
    // needs extract/structure and the shaping ops around them. Aggregates
    // are pointless here — scoring aggregates the corpus itself, in the
    // runner, and a pipeline-level aggregate would collapse the very rows
    // the labels join against.
    if (pipelineType === "eval") {
      return o.category !== "quality" && !["aggregate", "pivot"].includes(o.op);
    }
    return o.category !== "quality";
  });

  const update = (i: number, patch: Partial<StepShape>) =>
    onChange(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const remove = (i: number) => {
    onChange(steps.filter((_, j) => j !== i));
    onOpenChange(null);
  };

  /** Insert at an explicit position — the old panel could only append. */
  const insertAt = (i: number, step: StepShape) => {
    const next = [...steps];
    next.splice(i, 0, step);
    onChange(next);
    setAddAt(null);
    onOpenChange(i);
  };

  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= steps.length) return;
    const next = [...steps];
    const [moved] = next.splice(from, 1);
    if (!moved) return;
    next.splice(to, 0, moved);
    onChange(next);
  };

  /** The op menu, shared by the between-rows inserts and the footer button. */
  const OpMenu = ({ at }: { at: number }) => (
    <div className="px-3.5 py-3 bg-surface-2 border-b border-border">
      <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle mb-2">
        {at === steps.length ? `Add ${isQuality ? "check" : "step"}` : `Insert at ${at + 1}`}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5">
        {ops.map((o) => (
          <button
            key={`${o.op}-${o.mode ?? ""}`}
            type="button"
            onClick={() => insertAt(at, emptyStep(o.op, o.mode))}
            className="px-2 py-1.5 rounded-sm border border-border bg-surface text-[12px] text-text hover:border-accent hover:text-accent transition-colors"
          >
            {o.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={() => setAddAt(null)}
        className="mt-2 font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-text"
      >
        Cancel
      </button>
    </div>
  );

  /* Between-rows insert. Faint rather than invisible — an affordance that only
   * exists on hover is one nobody finds. The footer button below is the
   * primary, always-visible way in. */
  const InsertRow = ({ at }: { at: number }) => {
    if (readOnly) return null;
    if (addAt === at) return <OpMenu at={at} />;
    return (
      <button
        type="button"
        onClick={() => setAddAt(at)}
        className="group w-full flex items-center gap-2 px-3.5 py-1 border-b border-border text-left"
        aria-label={`Insert step at position ${at + 1}`}
      >
        <span className="font-mono text-[11px] text-subtle group-hover:text-accent w-[22px] text-center transition-colors">
          +
        </span>
        <span className="flex-1 h-px bg-border group-hover:bg-accent transition-colors" />
      </button>
    );
  };

  return (
    <Panel>
      <PanelHead
        label={label}
        count={
          <span className="flex items-center gap-2">
            {steps.length === 0 ? <span className="text-subtle">none</span> : steps.length}
            {!readOnly && (
              <AutoMapButton outputId={outputId} steps={steps} onChange={onChange} />
            )}
          </span>
        }
      />

      {steps.length === 0 && (
        <div className="px-4 py-6 text-center text-sm text-subtle">
          {readOnly
            ? `No ${label.toLowerCase()} defined.`
            : `No ${label.toLowerCase()} yet.`}
        </div>
      )}

      {steps.map((step, i) => {
        const targeted = openIndex === i;
        return (
          <div key={i}>
            {steps.length > 0 && i > 0 && <InsertRow at={i} />}
            <div
              id={`step-${i}`}
              ref={targeted ? targetRef : undefined}
              className={cn(
                "border-b border-border scroll-mt-32 transition-colors",
                targeted && "bg-[color:var(--accent-tint)]",
              )}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragFrom !== null) move(dragFrom, i);
                setDragFrom(null);
              }}
            >
              {/* Header: what this step is, plus its controls. */}
              <div className="grid grid-cols-[36px_1fr_auto] items-start group">
                <div className="py-3 text-center font-mono text-[11px] text-subtle border-r border-border self-stretch">
                  {i + 1}
                </div>

                <div className="px-3.5 py-2.5 min-w-0">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="font-mono text-[10px] font-bold tracking-[0.15em] uppercase text-accent px-1.5 py-0.5 rounded-sm bg-[color:var(--accent-tint)] shrink-0">
                      {labelFor(step)}
                    </span>
                    <span className="text-[13.5px] text-muted truncate">
                      {stepTitle(step)}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-1 px-2 py-2.5">
                  {!readOnly && (
                    <>
                      <span
                        draggable
                        onDragStart={() => setDragFrom(i)}
                        onDragEnd={() => setDragFrom(null)}
                        className="px-1 text-subtle hover:text-accent cursor-grab select-none"
                        title="Drag to reorder"
                      >
                        ⋮⋮
                      </span>
                      <button
                        type="button"
                        onClick={() => remove(i)}
                        title="Remove step"
                        className="px-1 text-subtle hover:text-red text-[15px] leading-none"
                      >
                        ×
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* Editor, always present. */}
              <div className="@container px-3.5 pb-3.5 pl-[50px]">
                {readOnly ? (
                  <StepSummary step={step} />
                ) : (
                  <StepIndexProvider index={i}>
                    <JoinOperandsProvider operands={operandsAt(i)}>
                      <StepEditor
                        step={step}
                        set={(patch) => update(i, patch as Partial<StepShape>)}
                      />
                    </JoinOperandsProvider>
                  </StepIndexProvider>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {!readOnly &&
        (addAt === steps.length ? (
          <OpMenu at={steps.length} />
        ) : (
          <AddStep
            onClick={() => setAddAt(steps.length)}
            label={isQuality ? "Add check" : "Add step"}
          />
        ))}
    </Panel>
  );
}
