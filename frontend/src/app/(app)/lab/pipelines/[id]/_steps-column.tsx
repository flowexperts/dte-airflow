"use client";

import { useEffect, useRef, useState } from "react";
import { Panel, PanelHead } from "@/components/ui";
import { StepEditor } from "@/components/builder/steps/editors";
import { StepIndexProvider } from "@/components/builder/schema-context";
import { StepSummary, stepTitle } from "@/components/builder/steps/summary";
import {
  STEP_OPS,
  emptyStep,
  labelFor,
  type StepShape,
} from "@/components/builder/steps/types";
import { cn } from "@/lib/cn";

/**
 * The ordered steps, readable first and editable second.
 *
 * The existing StepsPanel mounts every step's full editor permanently, which
 * makes a long pipeline unreadable. Here a step is a one-line summary until you
 * open it — the same component either way, so a step never reads differently
 * depending on which page you're on.
 */
export function StepsColumn({
  steps,
  onChange,
  pipelineType,
  openIndex,
  onOpenChange,
  readOnly,
}: {
  steps: StepShape[];
  onChange: (steps: StepShape[]) => void;
  pipelineType: "transform" | "quality";
  openIndex: number | null;
  onOpenChange: (i: number | null) => void;
  readOnly: boolean;
}) {
  const [addAt, setAddAt] = useState<number | null>(null);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const openRef = useRef<HTMLDivElement>(null);

  // Deep-linked step (#step-3 from a failed run) scrolls itself in.
  useEffect(() => {
    if (openIndex !== null) {
      openRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
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

  const ops = STEP_OPS.filter((o) =>
    isQuality
      ? o.category === "quality" ||
        ["filter", "rename", "select", "join"].includes(o.op)
      : o.category !== "quality",
  );

  const update = (i: number, patch: Partial<StepShape>) =>
    onChange(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const remove = (i: number) => {
    onChange(steps.filter((_, j) => j !== i));
    onOpenChange(null);
  };

  /** Insert at an explicit position — the old panel could only append. */
  const insertAt = (i: number, op: StepShape) => {
    const next = [...steps];
    next.splice(i, 0, op);
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
    onOpenChange(null);
  };

  const AddRow = ({ at }: { at: number }) =>
    readOnly ? null : addAt === at ? (
      <div className="px-3.5 py-3 bg-surface-2 border-b border-border">
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
    ) : (
      <button
        type="button"
        onClick={() => setAddAt(at)}
        className="group w-full flex items-center gap-2 px-3.5 py-1 border-b border-border text-left"
        aria-label={`Insert step at position ${at + 1}`}
      >
        <span className="font-mono text-[11px] text-transparent group-hover:text-accent w-[22px] text-center transition-colors">
          +
        </span>
        <span className="flex-1 h-px bg-transparent group-hover:bg-[color:var(--accent-tint)] transition-colors" />
      </button>
    );

  return (
    <Panel>
      <PanelHead
        label={label}
        count={
          steps.length === 0 ? (
            <span className="text-subtle">none</span>
          ) : (
            steps.length
          )
        }
      />

      {steps.length === 0 && (
        <div className="px-4 py-6 text-center text-sm text-subtle">
          {readOnly
            ? `No ${label.toLowerCase()} defined.`
            : `No ${label.toLowerCase()} yet — use + below.`}
        </div>
      )}

      {steps.map((step, i) => {
        const open = openIndex === i;
        return (
          <div key={i}>
            <AddRow at={i} />
            <div
              id={`step-${i}`}
              ref={open ? openRef : undefined}
              className={cn(
                "border-b border-border scroll-mt-32",
                open && "bg-surface-2",
              )}
              draggable={!readOnly && !open}
              onDragStart={() => setDragFrom(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragFrom !== null) move(dragFrom, i);
                setDragFrom(null);
              }}
              onDragEnd={() => setDragFrom(null)}
            >
              <div className="grid grid-cols-[36px_1fr_auto] group">
                <div className="py-3 text-center font-mono text-[11px] text-subtle border-r border-border group-hover:text-accent">
                  {i + 1}
                </div>

                <button
                  type="button"
                  onClick={() => onOpenChange(open ? null : i)}
                  className="py-3 px-3.5 min-w-0 text-left hover:bg-hover transition-colors"
                  aria-expanded={open}
                >
                  <div className="flex items-center gap-2.5 mb-1.5">
                    <span className="font-mono text-[10px] font-bold tracking-[0.15em] uppercase text-accent px-1.5 py-0.5 rounded-sm bg-[color:var(--accent-tint)] shrink-0">
                      {labelFor(step)}
                    </span>
                    <span className="text-[14.5px] font-medium text-text truncate">
                      {stepTitle(step)}
                    </span>
                  </div>
                  {!open && <StepSummary step={step} />}
                </button>

                <div className="flex items-center gap-1 px-2 border-l border-border">
                  {!readOnly && (
                    <>
                      <span
                        className="px-1 text-subtle cursor-grab select-none"
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

              {open && (
                <div className="px-3.5 pb-3.5 pl-[50px]">
                  {readOnly ? (
                    <StepSummary step={step} />
                  ) : (
                    <StepIndexProvider index={i}>
                      <StepEditor
                        step={step}
                        set={(patch) => update(i, patch as Partial<StepShape>)}
                      />
                    </StepIndexProvider>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}

      <AddRow at={steps.length} />
    </Panel>
  );
}
