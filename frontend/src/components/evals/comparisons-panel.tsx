"use client";

import Link from "next/link";
import useSWR from "swr";
import { Panel, PanelHead, Pill } from "@/components/ui";
import { listPipelineComparisons, type PipelineComparison } from "@/lib/api";
import { ScoreBar } from "./score";
import { rootPipelineId } from "@/lib/pipeline-variant";

/**
 * Comparisons already run for this pipeline.
 *
 * The compare page shipped reachable only from the redirect fired once at
 * launch: navigate away and the comparison was gone unless you had kept the
 * URL. Exactly the "creatable and reachable from nowhere" failure plan 053
 * was written to fix in plan 051's surfaces, reintroduced one surface along.
 *
 * Renders nothing when there are none — a panel saying "no comparisons yet"
 * on every pipeline that will never have one is noise, and Compare… is
 * already sitting in the header explaining itself.
 */
/**
 * Shared by the panel and the tab badge, so the count beside "Comparisons"
 * and the list under it are one fetch and can never disagree.
 */
export function usePipelineComparisons(pipelineId: string) {
  return useSWR(
    ["comparisons", pipelineId],
    () => listPipelineComparisons(pipelineId),
    // Any comparison still filling in keeps the list fresh, so a run
    // finishing elsewhere shows up without a reload.
    {
      refreshInterval: (latest) =>
        (latest?.comparisons ?? []).some((c) => c.pending > 0) ? 5000 : 0,
    },
  );
}

export function ComparisonsPanel({ pipelineId }: { pipelineId: string }) {
  const { data } = usePipelineComparisons(pipelineId);

  const rows = data?.comparisons ?? [];
  if (rows.length === 0) return null;

  // Links point at the root: a comparison launched from a cell belongs to
  // the config that was authored, and that is the page carrying this panel.
  const root = data?.pipeline_id ?? rootPipelineId(pipelineId);

  return (
    <Panel>
      <PanelHead label="Comparisons" count={rows.length} />
      <div className="flex flex-col">
        {rows.map((c: PipelineComparison) => (
          <Link
            key={c.sweep_id}
            href={`/pipelines/${encodeURIComponent(root)}/compare?sweep=${encodeURIComponent(c.sweep_id)}`}
            className="px-4 py-2.5 border-b border-border last:border-b-0 hover:bg-hover flex items-center gap-3"
          >
            <span className="text-[12.5px] text-text">
              {c.cells} config{c.cells === 1 ? "" : "s"}
            </span>
            {c.pending > 0 && <Pill status="running">{c.pending} running</Pill>}
            {/* Absent, not zero. Most comparisons in this flow are never
                labelled, and 0% would read as "every config failed". */}
            {c.best_macro_f1 != null && (
              <ScoreBar value={c.best_macro_f1} width={72} />
            )}
            <span className="ml-auto font-mono text-[11px] text-subtle">
              {c.started_at ? new Date(c.started_at).toLocaleDateString() : "—"}
            </span>
          </Link>
        ))}
      </div>
    </Panel>
  );
}

/**
 * The Comparisons tab.
 *
 * The panel above renders nothing when the list is empty — right for a rail
 * slot, wrong for a tab: a tab you can click to reach a blank page reads as
 * broken. So the tab carries an empty state naming the control that fills
 * it, and the tab itself is only offered on pipelines that can be compared.
 */
export function ComparisonsPane({ pipelineId }: { pipelineId: string }) {
  const { data, isLoading } = usePipelineComparisons(pipelineId);
  const rows = data?.comparisons ?? [];

  if (isLoading && rows.length === 0) {
    return <p className="text-[12.5px] text-muted">Loading comparisons…</p>;
  }

  if (rows.length === 0) {
    return (
      <Panel>
        <div className="px-4 py-4 text-[12.5px] text-muted max-w-[62ch]">
          No comparisons yet. Choose{" "}
          <strong className="text-text">Compare…</strong> in the header to run
          the same documents through several configs and see where they
          disagree — no labels needed.
        </div>
      </Panel>
    );
  }

  return <ComparisonsPanel pipelineId={pipelineId} />;
}
