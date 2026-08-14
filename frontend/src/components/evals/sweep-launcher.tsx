"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Dropdown, Input, Panel, PanelHead } from "@/components/ui";
import {
  launchSweep,
  listPipelines,
  previewSweep,
  type Pipeline,
  type SweepEstimate,
} from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { usePermissions } from "@/lib/use-permissions";

/**
 * The sweep launcher, which is mostly a confirmation dialog with a matrix
 * builder attached.
 *
 * A cartesian product of providers × models × prompts over a few hundred
 * documents is real money. The estimate is therefore not decoration: the
 * first call always previews and enqueues nothing, and the launch button
 * only appears once someone has seen a cell count. A launcher that can
 * spend a four-figure sum on a mis-click is a launcher people stop using,
 * which is worse than one that takes two clicks.
 *
 * `uncached_calls` is deliberately labelled a *ceiling*, not a forecast.
 * Plan 050 caches extraction by document content and structure by text
 * hash, so a re-run of a cell already evaluated costs nothing — quoting the
 * worst case as if it were the price would scare people off the cheap
 * operation the caching exists to make cheap.
 */
export function SweepLauncher({ evalSetId }: { evalSetId: string }) {
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  const [pipelineId, setPipelineId] = useState("");
  const [axis, setAxis] = useState("provider");
  const [values, setValues] = useState("claude, openai");
  const [estimate, setEstimate] = useState<SweepEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();

  const { data: pipelines } = useSWR<Pipeline[]>(
    open ? ["pipelines", "sweep"] : null,
    () => listPipelines(),
  );
  const evalPipelines = (pipelines ?? []).filter((p) => p.pipeline_type === "eval");

  const matrix = () => {
    const parsed = values
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
    return { [axis.trim()]: parsed };
  };

  const preview = async () => {
    setBusy(true);
    setErr(null);
    setEstimate(null);
    try {
      setEstimate(await previewSweep(evalSetId, pipelineId, matrix()));
    } catch (e) {
      setErr(humanizeError(e, { action: "estimate", entity: "sweep" }).message);
    } finally {
      setBusy(false);
    }
  };

  const launch = async () => {
    setBusy(true);
    try {
      const res = await launchSweep(evalSetId, pipelineId, matrix());
      toast.success({
        title: `Launched ${res.runs?.length ?? res.cells} runs`,
        message: "They'll appear on the leaderboard as they finish.",
      });
      setOpen(false);
      setEstimate(null);
    } catch (e) {
      toast.error(humanizeError(e, { action: "launch", entity: "sweep" }));
    } finally {
      setBusy(false);
    }
  };

  if (!can("eval:write")) return null;

  if (!open) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        Sweep…
      </Button>
    );
  }

  const cellCount = values.split(",").map((v) => v.trim()).filter(Boolean).length;

  return (
    <Panel>
      <PanelHead label="Sweep" />
      <div className="px-4 py-3 flex flex-col gap-3">
        <p className="text-[12.5px] text-muted">
          Run one config across several values and score each against this
          corpus. Extraction is cached by document content, so the PDFs are
          parsed once no matter how many cells you run.
        </p>

        <Dropdown
          value={pipelineId}
          onChange={(v) => {
            setPipelineId(v);
            setEstimate(null);
          }}
          placeholder={
            evalPipelines.length === 0 ? "No eval pipelines yet" : "— base pipeline —"
          }
          options={evalPipelines.map((p) => ({ value: p.id, label: p.name }))}
        />

        <div className="grid grid-cols-[200px_1fr] gap-2">
          <Input
            value={axis}
            onChange={(e) => {
              setAxis(e.target.value);
              setEstimate(null);
            }}
            placeholder="provider"
          />
          <Input
            value={values}
            onChange={(e) => {
              setValues(e.target.value);
              setEstimate(null);
            }}
            placeholder="claude, openai"
          />
        </div>
        <p className="text-[11.5px] text-subtle">
          The axis is a dotted path into the structure step —{" "}
          <code className="font-mono">provider</code> or{" "}
          <code className="font-mono">model.instructions</code>. Values are
          comma-separated. A name that isn&apos;t on the step is rejected rather
          than ignored, so a typo can&apos;t become {cellCount} identical cells.
        </p>

        {err && <p className="text-[12.5px] text-red">{err}</p>}

        {estimate && (
          <div className="rounded-[var(--radius)] border border-border px-3 py-2 flex flex-col gap-1">
            <div className="flex gap-6 font-mono text-[12px] tabular-nums">
              <span>
                <span className="text-subtle">cells </span>
                {estimate.cells}
              </span>
              <span>
                <span className="text-subtle">documents </span>
                {estimate.documents}
              </span>
              <span>
                <span className="text-subtle">calls ≤ </span>
                {estimate.uncached_calls}
              </span>
              <span>
                <span className="text-subtle">cost ≤ </span>
                {estimate.est_cost_usd == null
                  ? "unknown"
                  : `$${estimate.est_cost_usd.toFixed(2)}`}
              </span>
            </div>
            <span className="text-[11.5px] text-subtle">
              Calls are a ceiling assuming nothing is cached. Anything you have
              already run is free.
            </span>
            {/* Extrapolated from a real measured run, or absent. Quoting a
                confident price nobody measured is worse than admitting we
                cannot price it yet — the invented number gets budgeted
                against. */}
            {estimate.cost_basis && (
              <span className="text-[11.5px] text-subtle">{estimate.cost_basis}</span>
            )}
          </div>
        )}

        <div className="flex items-center gap-2">
          <Button
            variant="default"
            size="sm"
            disabled={busy || !pipelineId || cellCount === 0}
            onClick={() => void preview()}
          >
            {busy ? "Estimating…" : "Estimate"}
          </Button>
          {/* Only reachable once an estimate has been seen. */}
          <Button
            variant="primary"
            size="sm"
            disabled={busy || !estimate}
            onClick={() => void launch()}
          >
            {estimate ? `Launch ${estimate.cells} runs` : "Launch"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setOpen(false);
              setEstimate(null);
            }}
          >
            Cancel
          </Button>
        </div>
      </div>
    </Panel>
  );
}
