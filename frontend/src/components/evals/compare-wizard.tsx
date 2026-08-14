"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Panel, PanelHead, Textarea } from "@/components/ui";
import {
  evalSetForPipeline,
  launchSweep,
  pipelineAsEval,
  previewSweep,
  type Pipeline,
  type SweepEstimate,
} from "@/lib/api";
import {
  buildMatrix,
  cellCount,
  regexAvailability,
  type CompareDraft,
  type FieldPattern,
} from "@/lib/compare-matrix";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { cn } from "@/lib/cn";

/**
 * Compare several extraction configs against the pipeline's own documents.
 *
 * This replaces a launcher that asked for a dotted axis path and a
 * comma-separated value list, reachable only from an eval set the user had
 * to define by hand first. Reaching a provider comparison took 28 steps and
 * could not actually be completed in the UI.
 *
 * Everything the old path made you declare is derived here: the eval twin,
 * the eval set, the field specs. The user picks what to vary and reads a
 * price. Four steps.
 *
 * Two rules kept from the launcher because both were right:
 *
 * **Estimate before launch.** A cartesian product over a few hundred
 * documents is real money, and Launch stays unreachable until a cell count
 * and a price have been seen.
 *
 * **Calls are a ceiling, not a forecast.** Extraction is cached by document
 * content, so re-running a cell already evaluated costs nothing. Quoting
 * the worst case as if it were the bill would scare people off the cheap
 * operation the caching exists to create.
 */

const PROVIDERS = [
  { id: "claude", label: "Claude", hint: "strongest on messy layouts" },
  { id: "openai", label: "OpenAI", hint: "" },
  { id: "regex", label: "Regex", hint: "free, offline, exact provenance" },
];

const MODELS: Record<string, { id: string; label: string }[]> = {
  claude: [
    { id: "claude-opus-5", label: "Opus 5" },
    { id: "claude-sonnet-5", label: "Sonnet 5" },
    { id: "claude-haiku-4-5", label: "Haiku 4.5" },
  ],
  openai: [
    { id: "gpt-5", label: "GPT-5" },
    { id: "gpt-5-mini", label: "GPT-5 mini" },
  ],
};

function structureFields(pipeline: Pipeline): FieldPattern[] {
  const step = (pipeline.steps ?? []).find(
    (s) => (s as { op?: string }).op === "structure",
  ) as { model?: { fields?: FieldPattern[] } } | undefined;
  return step?.model?.fields ?? [];
}

function Chip({
  active,
  disabled,
  onClick,
  children,
  title,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "px-2.5 py-1 rounded-[var(--radius)] border text-[12.5px] cursor-pointer",
        active
          ? "border-accent bg-accent/10 text-text"
          : "border-border bg-transparent text-muted hover:bg-hover",
        disabled && "opacity-40 cursor-not-allowed hover:bg-transparent",
      )}
    >
      {children}
    </button>
  );
}

export function CompareWizard({
  pipeline,
  onClose,
}: {
  pipeline: Pipeline;
  onClose: () => void;
}) {
  const router = useRouter();
  const toast = useToast();
  const [draft, setDraft] = useState<CompareDraft>({
    providers: ["claude", "openai"],
    models: [],
    instructions: [],
  });
  const [estimate, setEstimate] = useState<SweepEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showPrompts, setShowPrompts] = useState(false);

  const fields = useMemo(() => structureFields(pipeline), [pipeline]);
  const regex = useMemo(() => regexAvailability(fields), [fields]);
  const cells = cellCount(draft);

  // Any edit invalidates the price that was approved. Keeping a stale
  // estimate visible next to a changed matrix is how someone launches 12
  // cells having agreed to 3.
  const update = (patch: Partial<CompareDraft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setEstimate(null);
    setErr(null);
  };

  const toggle = (key: keyof CompareDraft, value: string) => {
    const current = draft[key];
    update({
      [key]: current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value],
    } as Partial<CompareDraft>);
  };

  const offeredModels = draft.providers.flatMap((p) => MODELS[p] ?? []);

  /**
   * Derive the twin and the set, then ask the API what this costs.
   *
   * Both derivations are idempotent, so running them on every estimate is
   * safe and keeps the launch path a single call.
   */
  const prepare = async () => {
    const { pipeline_id } = await pipelineAsEval(pipeline.id);
    const { eval_set_id } = await evalSetForPipeline(pipeline_id);
    return { pipelineId: pipeline_id, evalSetId: eval_set_id };
  };

  const estimateRun = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { pipelineId, evalSetId } = await prepare();
      setEstimate(await previewSweep(evalSetId, pipelineId, buildMatrix(draft)));
    } catch (e) {
      setErr(humanizeError(e, { action: "estimate", entity: "comparison" }).message);
    } finally {
      setBusy(false);
    }
  };

  const launch = async () => {
    setBusy(true);
    try {
      const { pipelineId, evalSetId } = await prepare();
      const res = await launchSweep(evalSetId, pipelineId, buildMatrix(draft));
      toast.success({
        title: `Comparing ${res.cells} config${res.cells === 1 ? "" : "s"}`,
        message: "Results fill in as each finishes.",
      });
      onClose();
      router.push(
        `/pipelines/${encodeURIComponent(pipeline.id)}/compare?sweep=${encodeURIComponent(res.sweep_id ?? "")}`,
      );
    } catch (e) {
      toast.error(humanizeError(e, { action: "launch", entity: "comparison" }));
      setBusy(false);
    }
  };

  return (
    <Panel className="absolute right-0 top-9 z-20 w-[440px] shadow-lg">
      <PanelHead label="Compare configs" />
      <div className="px-4 py-3 flex flex-col gap-4">
        <p className="text-[12.5px] text-muted">
          Run this pipeline&apos;s extraction several ways over the same
          documents and see where they differ. No labels needed — PDFs are
          parsed once and shared across every config.
        </p>

        <div className="flex flex-col gap-1.5">
          <span className="text-[11.5px] text-subtle uppercase tracking-wide">
            Provider
          </span>
          <div className="flex gap-1.5 flex-wrap">
            {PROVIDERS.map((p) => {
              const blocked = p.id === "regex" && !regex.available;
              return (
                <Chip
                  key={p.id}
                  active={draft.providers.includes(p.id)}
                  disabled={blocked}
                  onClick={() => toggle("providers", p.id)}
                  title={p.hint}
                >
                  {p.label}
                </Chip>
              );
            })}
          </div>
          {/* Naming the fields matters. "Add patterns" is not actionable;
              this tells them which ones and where to go. Offering regex
              anyway would produce a cell that runs, returns nulls, and
              scores near zero — a result that looks like a measurement. */}
          {!regex.available && (
            <p className="text-[11.5px] text-subtle">
              Regex needs a pattern on every field.{" "}
              {regex.missing.length > 0 ? (
                <>
                  <span className="font-mono">{regex.missing.join(", ")}</span>{" "}
                  {regex.missing.length === 1 ? "has" : "have"} none — add{" "}
                  {regex.missing.length === 1 ? "one" : "them"} on the structure
                  step to compare against it.
                </>
              ) : (
                "This pipeline declares no fields."
              )}
            </p>
          )}
        </div>

        {offeredModels.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[11.5px] text-subtle uppercase tracking-wide">
              Model <span className="normal-case">— optional</span>
            </span>
            <div className="flex gap-1.5 flex-wrap">
              {offeredModels.map((m) => (
                <Chip
                  key={m.id}
                  active={draft.models.includes(m.id)}
                  onClick={() => toggle("models", m.id)}
                >
                  {m.label}
                </Chip>
              ))}
            </div>
            <p className="text-[11.5px] text-subtle">
              Leave empty to use each provider&apos;s default.
            </p>
          </div>
        )}

        {!showPrompts ? (
          <button
            type="button"
            onClick={() => setShowPrompts(true)}
            className="text-[12px] text-muted hover:text-text text-left bg-transparent cursor-pointer"
          >
            + Compare prompts too
          </button>
        ) : (
          <div className="flex flex-col gap-1.5">
            <span className="text-[11.5px] text-subtle uppercase tracking-wide">
              Instructions
            </span>
            {[0, 1, 2].map((i) => (
              <Textarea
                key={i}
                rows={2}
                value={draft.instructions[i] ?? ""}
                placeholder={i === 0 ? "e.g. Ignore the remittance stub." : "another variant"}
                onChange={(e) => {
                  const next = [...draft.instructions];
                  next[i] = e.target.value;
                  update({ instructions: next });
                }}
              />
            ))}
            <p className="text-[11.5px] text-subtle">
              Blank boxes are skipped. Regex ignores instructions entirely.
            </p>
          </div>
        )}

        {err && <p className="text-[12.5px] text-red">{err}</p>}

        {estimate && (
          <div className="rounded-[var(--radius)] border border-border px-3 py-2 flex flex-col gap-1">
            <div className="flex gap-5 font-mono text-[12px] tabular-nums flex-wrap">
              <span>
                <span className="text-subtle">configs </span>
                {estimate.cells}
              </span>
              <span>
                <span className="text-subtle">documents </span>
                {estimate.documents}
              </span>
              <span>
                <span className="text-subtle">cost ≤ </span>
                {estimate.est_cost_usd == null
                  ? "unknown"
                  : `$${estimate.est_cost_usd.toFixed(2)}`}
              </span>
            </div>
            <span className="text-[11.5px] text-subtle">
              A ceiling assuming nothing is cached. Anything already run is free.
            </span>
            {/* Extrapolated from a measured run, or absent. A confident
                price nobody measured gets budgeted against. */}
            {estimate.cost_basis && (
              <span className="text-[11.5px] text-subtle">{estimate.cost_basis}</span>
            )}
            {/* Why the count is lower than providers × models. Silently
                running fewer cells than someone built would leave them
                looking for a column that never appears. */}
            {estimate.dropped && estimate.dropped.length > 0 && (
              <div className="flex flex-col gap-0.5 pt-1 border-t border-border">
                <span className="text-[11.5px] text-subtle">
                  {estimate.dropped.length} combination
                  {estimate.dropped.length === 1 ? "" : "s"} skipped:
                </span>
                {estimate.dropped.slice(0, 3).map((d, i) => (
                  <span key={i} className="text-[11.5px] text-subtle">
                    {d.reason}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="flex items-center gap-2">
          <Button
            /* Primary while it is the step to take. A cartesian product over
               a few hundred documents is real money, so the price comes
               before the spend — but that only works if the first button is
               visibly the first button. */
            variant={estimate ? "default" : "primary"}
            size="sm"
            disabled={busy || cells < 1}
            onClick={() => void estimateRun()}
          >
            {busy ? "Working…" : cells > 0 ? `Estimate ${cells}` : "Estimate"}
          </Button>
          {/* Unreachable until a price has been seen — and muted until then,
              because primary styling on an inert control says "press this"
              and is wrong. */}
          <Button
            variant={estimate ? "primary" : "default"}
            size="sm"
            disabled={busy || !estimate}
            onClick={() => void launch()}
          >
            {estimate ? `Run ${estimate.cells}` : "Run"}
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
        </div>

        {/* DESIGN.md: no disabled button whose enabling condition is not
            stated on screen. Without this, Run looks broken rather than
            gated, and the two-step guard reads as a bug. */}
        {!estimate && (
          <p className="text-[11.5px] text-subtle">
            {cells < 1
              ? "Tick at least one provider to compare."
              : "Estimate first — it shows the cost and runs nothing. Run unlocks once you've seen it."}
          </p>
        )}
      </div>
    </Panel>
  );
}
