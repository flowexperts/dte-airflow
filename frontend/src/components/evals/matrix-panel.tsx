import { useMemo, useState } from "react";
import { useRouter } from "@/lib/nav";
import useSWR from "swr";
import { Button, Panel, PanelHead, Textarea } from "@/components/ui";
import {
  evalSetForPipeline,
  getStructureProviderStatus,
  launchSweep,
  previewSweep,
  type Pipeline,
  type SweepEstimate,
} from "@/lib/api";
import {
  MODELS,
  PROVIDERS,
  buildMatrix,
  cellCount,
  draftFromMatrix,
  regexAvailability,
  unknownAxes,
  type CompareDraft,
  type FieldPattern,
} from "@/lib/compare-matrix";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { cn } from "@/lib/cn";

/**
 * The comparison an eval pipeline runs, edited where the pipeline is.
 *
 * This replaces the Compare wizard, whose matrix was transient: posted once
 * to the sweep endpoint and never stored. You could not reopen a
 * comparison, change one axis and re-run it — you started from an empty
 * form and minted a fresh set of variant pipelines each time, which is how
 * one demo pipeline accumulated twelve variants.
 *
 * An eval run *is* a comparison run. Making the matrix a property of the
 * pipeline is what makes that true of the object model rather than only of
 * the wizard, and it is what lets a scheduled eval run be a comparison at
 * all.
 *
 * Edits go through the pipeline's own `onChange`/save, so there is no
 * second dirty state and no second Save button. Run always posts what is on
 * screen — the API takes the body over the stored matrix — so an unsaved
 * tweak can still be priced and run; saving is what keeps it for next time.
 */

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

export function MatrixPanel({
  pipeline,
  onChange,
  readOnly,
}: {
  pipeline: Pipeline;
  onChange: (matrix: Record<string, string[]> | null) => void;
  readOnly?: boolean;
}) {
  const router = useRouter();
  const toast = useToast();
  const [estimate, setEstimate] = useState<SweepEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showPrompts, setShowPrompts] = useState(false);

  const stored = (pipeline.matrix ?? null) as Record<string, unknown[]> | null;
  /* The pipeline is the single source of truth — no local draft mirroring
     it. A second copy would need syncing back on every keystroke, which is
     the bug class the step editors already document. */
  const draft = useMemo(() => draftFromMatrix(stored), [stored]);
  const foreign = useMemo(() => unknownAxes(stored), [stored]);

  const fields = useMemo(() => structureFields(pipeline), [pipeline]);
  const regex = useMemo(() => regexAvailability(fields), [fields]);

  const { data: status } = useSWR("provider-status", getStructureProviderStatus);
  const providerStatus = useMemo(() => status?.providers ?? {}, [status]);

  /* What can actually run, derived rather than synced. An effect that
     rewrote the matrix when readiness arrived would fight the user's clicks
     and re-fire on every refetch (and trips
     `react-hooks/set-state-in-effect`). What was ticked stays stored; what
     is runnable is computed. */
  const effective: CompareDraft = useMemo(
    () => ({
      ...draft,
      providers: draft.providers.filter(
        (p) => providerStatus[p]?.configured !== false,
      ),
    }),
    [draft, providerStatus],
  );

  /* No axes is N=1 — this pipeline's own config, run once. That is the
     nightly regression check, not an empty comparison. */
  const cells = cellCount(effective) || 1;

  const update = (patch: Partial<CompareDraft>) => {
    const next = buildMatrix({ ...draft, ...patch });
    // Any edit invalidates the price that was approved. A stale estimate
    // beside a changed matrix is how someone runs 12 cells having agreed
    // to 3.
    setEstimate(null);
    setErr(null);
    // Preserve axes this panel has no controls for rather than deleting a
    // user's configuration as a side effect of ticking a chip.
    for (const key of foreign) next[key] = (stored?.[key] ?? []).map(String);
    onChange(Object.keys(next).length > 0 ? next : null);
  };

  const toggle = (key: keyof CompareDraft, value: string) => {
    const current = draft[key];
    update({
      [key]: current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value],
    } as Partial<CompareDraft>);
  };

  const estimateRun = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { eval_set_id } = await evalSetForPipeline(pipeline.id);
      setEstimate(
        await previewSweep(eval_set_id, pipeline.id, buildMatrix(effective)),
      );
    } catch (e) {
      setErr(humanizeError(e, { action: "estimate", entity: "comparison" }).message);
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    setBusy(true);
    try {
      const { eval_set_id } = await evalSetForPipeline(pipeline.id);
      const res = await launchSweep(eval_set_id, pipeline.id, buildMatrix(effective));
      toast.success({
        title:
          res.cells === 1
            ? "Running this config"
            : `Comparing ${res.cells} configs`,
        message: "Results fill in as each finishes.",
      });
      router.push(
        `/pipelines/compare?id=${encodeURIComponent(pipeline.id)}&sweep=${encodeURIComponent(res.sweep_id ?? "")}`,
      );
    } catch (e) {
      toast.error(humanizeError(e, { action: "run", entity: "comparison" }));
      setBusy(false);
    }
  };

  const offeredModels = effective.providers.flatMap((p) => MODELS[p] ?? []);

  return (
    <Panel>
      <PanelHead
        label="Comparison"
        count={
          <span className="font-mono text-[11px] text-subtle">
            {cells} config{cells === 1 ? "" : "s"}
          </span>
        }
      />
      <div className="px-4 py-3 flex flex-col gap-4">
        <p className="text-[12.5px] text-muted max-w-[68ch]">
          Run this pipeline&apos;s extraction several ways over the same
          documents and see where they differ. No labels needed — PDFs are
          parsed once and shared across every config. Leave everything
          unticked to run the single config below as it stands.
        </p>

        <div className="flex flex-col gap-1.5">
          <span className="text-[11.5px] text-subtle uppercase tracking-wide">
            Provider
          </span>
          <div className="flex gap-1.5 flex-wrap">
            {PROVIDERS.map((p) => {
              const unconfigured = providerStatus[p.id]?.configured === false;
              const blocked =
                readOnly || (p.id === "regex" && !regex.available) || unconfigured;
              return (
                <Chip
                  key={p.id}
                  active={effective.providers.includes(p.id)}
                  disabled={blocked}
                  onClick={() => toggle("providers", p.id)}
                  title={providerStatus[p.id]?.reason ?? p.hint}
                >
                  {p.label}
                </Chip>
              );
            })}
          </div>
          {/* Names the variable to set. "Claude is unavailable" sends
              someone to check their pipeline; this sends them to the right
              place. */}
          {PROVIDERS.filter((p) => providerStatus[p.id]?.configured === false).map((p) => (
            <p key={p.id} className="text-[11.5px] text-subtle">
              {providerStatus[p.id]?.reason}
            </p>
          ))}
          {/* Naming the fields matters: "add patterns" is not actionable.
              Offering regex anyway produces a cell that runs, returns
              nulls and scores near zero — a result that looks like a
              measurement and is not one. */}
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
                  // `exactOptionalPropertyTypes`: an optional prop rejects an
                  // explicit `undefined`, so coerce rather than pass through.
                  disabled={readOnly ?? false}
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

        {!showPrompts && draft.instructions.length === 0 ? (
          <button
            type="button"
            disabled={readOnly}
            onClick={() => setShowPrompts(true)}
            className="text-[12px] text-muted hover:text-text text-left bg-transparent cursor-pointer disabled:opacity-40"
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
                readOnly={readOnly}
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

        {/* A saved axis with no control here must not vanish on the next
            edit, and pretending it isn't there would be worse. */}
        {foreign.length > 0 && (
          <p className="text-[11.5px] text-subtle">
            Also varying{" "}
            <span className="font-mono">{foreign.join(", ")}</span>, set
            outside this panel and kept as-is.
          </p>
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
            {estimate.cost_basis && (
              <span className="text-[11.5px] text-subtle">{estimate.cost_basis}</span>
            )}
            {/* Why the count is lower than providers × models. Silently
                running fewer cells than someone built leaves them looking
                for a column that never appears. */}
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
            variant={estimate ? "default" : "primary"}
            size="sm"
            disabled={busy}
            onClick={() => void estimateRun()}
          >
            {busy ? "Working…" : `Estimate ${cells}`}
          </Button>
          {/* Unreachable until a price has been seen, and muted until then:
              primary styling on an inert control says "press this". */}
          <Button
            variant={estimate ? "primary" : "default"}
            size="sm"
            disabled={busy || !estimate}
            onClick={() => void run()}
          >
            {estimate
              ? estimate.cells === 1
                ? "Run eval"
                : `Compare ${estimate.cells} configs`
              : cells === 1
                ? "Run eval"
                : "Compare"}
          </Button>
        </div>

        {/* DESIGN.md: no disabled button whose enabling condition is not
            stated on screen. Without this the guard reads as a broken
            control rather than a deliberate one. */}
        {!estimate && (
          <p className="text-[11.5px] text-subtle">
            Estimate first — it shows the cost and runs nothing.{" "}
            {cells === 1 ? "Run" : "Compare"} unlocks once you&apos;ve seen it.
          </p>
        )}
      </div>
    </Panel>
  );
}
