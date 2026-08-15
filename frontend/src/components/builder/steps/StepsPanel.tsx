"use client";

import { useState } from "react";
import { Panel, PanelHead } from "@/components/ui";
import { STEP_OPS, emptyStep, labelFor, type StepShape } from "./types";
import { StepEditor } from "./editors";
import { StepIndexProvider } from "../schema-context";

export function StepsPanel({
  steps,
  onChange,
  pipelineType = "transform",
}: {
  steps: StepShape[];
  onChange: (next: StepShape[]) => void;
  pipelineType?: "transform" | "quality" | "eval";
}) {
  const [addOpen, setAddOpen] = useState(false);

  const update = (i: number, patch: Partial<StepShape>) => {
    const current = steps[i];
    if (!current) return;
    const copy = [...steps];
    copy[i] = { ...current, ...patch };
    onChange(copy);
  };
  const remove = (i: number) =>
    onChange(steps.filter((_, j) => j !== i));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= steps.length) return;
    const a = steps[i];
    const b = steps[j];
    if (!a || !b) return;
    const copy = [...steps];
    copy[i] = b;
    copy[j] = a;
    onChange(copy);
  };
  const add = (op: string, mode?: string) => {
    onChange([...steps, emptyStep(op as StepShape["op"], mode as StepShape["mode"])]);
    setAddOpen(false);
  };

  const filteredOps = STEP_OPS.filter((o) => {
    if (pipelineType === "quality") {
      return o.category === "quality" || ["filter", "rename", "select", "join"].includes(o.op);
    }
    // An eval pipeline's job is to produce the fields being scored, so it
    // needs extract/structure and the shaping ops around them. Aggregates
    // are pointless here — scoring aggregates the corpus itself, in the
    // runner, and a pipeline-level aggregate would collapse the very rows
    // the labels join against.
    if (pipelineType === "eval") {
      return (
        o.category !== "quality" && !["aggregate", "pivot"].includes(o.op)
      );
    }
    return o.category !== "quality";
  });

  return (
    <Panel>
      <PanelHead label="Ordered steps" count={steps.length} />
      {steps.length === 0 && (
        <div className="p-6 text-center text-sm text-subtle">
          No steps yet. Add one below.
        </div>
      )}
      {steps.map((step, i) => (
        <div key={i} className="border-b border-border last:border-b-0">
          <div className="grid grid-cols-[36px_1fr_auto] items-center">
            <div className="text-center font-mono text-[11px] text-subtle py-3 border-r border-border">
              {i + 1}
            </div>
            <div className="@container px-3.5 py-2.5">
              <div className="flex items-center justify-between mb-2">
                <span className="font-mono text-[10px] font-bold tracking-[0.15em] uppercase text-accent px-1.5 py-0.5 rounded-sm bg-[color:var(--accent-tint)]">
                  {labelFor(step)}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => move(i, -1)}
                    className="text-subtle hover:text-text px-1"
                    title="Move up"
                  >↑</button>
                  <button
                    type="button"
                    onClick={() => move(i, 1)}
                    className="text-subtle hover:text-text px-1"
                    title="Move down"
                  >↓</button>
                  <button
                    type="button"
                    onClick={() => remove(i)}
                    className="text-subtle hover:text-red px-1"
                    title="Remove"
                  >×</button>
                </div>
              </div>
              <StepIndexProvider index={i}>
                <StepEditor step={step} set={(patch) => update(i, patch)} />
              </StepIndexProvider>
            </div>
            <div />
          </div>
        </div>
      ))}
      {addOpen ? (
        <div className="p-3 border-t border-dashed border-border grid grid-cols-2 md:grid-cols-3 gap-1.5 bg-surface-2">
          {filteredOps.map((op) => (
            <button
              key={`${op.op}-${op.mode ?? ""}`}
              type="button"
              onClick={() => add(op.op, op.mode)}
              className="text-left px-2.5 py-1.5 text-[12.5px] border border-border rounded hover:border-accent hover:text-accent bg-surface transition-colors"
            >
              {op.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setAddOpen(false)}
            className="col-span-full text-center py-1.5 text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-text font-mono"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAddOpen(true)}
          className="w-full text-center py-3 px-3.5 border-t border-dashed border-border font-medium text-xs text-subtle hover:text-accent hover:bg-[color:var(--accent-tint)] transition-colors"
        >
          <span className="text-accent font-bold mr-1">+</span> Add step
        </button>
      )}
    </Panel>
  );
}
