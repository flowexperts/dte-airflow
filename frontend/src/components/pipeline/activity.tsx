"use client";

import useSWR from "swr";
import { Panel } from "@/components/ui";
import { HistoryPanel } from "@/components/builder/history/HistoryPanel";
import { RunsTable } from "@/components/runs-table";
import { listPipelineRuns, type Run } from "@/lib/api";

/**
 * Past-tense views of a pipeline, as page-level panes rather than a section.
 *
 * They used to sit below the canvas. That works at ten steps and fails
 * completely at three hundred: anything anchored to the end of the document
 * is unreachable when the document has no bounded end. Every editor is open,
 * so a long pipeline is tens of thousands of pixels tall and a footer section
 * is effectively deleted.
 *
 * So Runs and History became tabs next to the spec instead of content beneath
 * it. Switching costs one click from any scroll position, they get the full
 * page width the run table's error column and the revision diff need, and
 * neither competes with Preview — which stays in the rail because it is
 * present tense and re-runs as you type.
 */

/** Shared by the panes and by the tab badge, so one fetch serves both. */
export function usePipelineRuns(pipelineId: string) {
  const { data } = useSWR<Run[]>(
    ["pipeline-runs", pipelineId],
    () => listPipelineRuns(pipelineId, 20),
    {
      refreshInterval: (latest) =>
        latest?.some((r) => r.status === "running" || r.status === "pending")
          ? 3000
          : 0,
    },
  );
  return data ?? [];
}

export function RunsPane({ runs }: { runs: Run[] }) {
  if (runs.length === 0) {
    return (
      <Panel>
        <div className="px-4 py-16 text-center text-sm text-subtle">
          Never run. Trigger it from the header to see results here.
        </div>
      </Panel>
    );
  }
  return (
    <Panel>
      <div className="p-3">
        <RunsTable runs={runs} />
      </div>
    </Panel>
  );
}

export function HistoryPane({ pipelineId }: { pipelineId: string }) {
  return (
    <Panel>
      <div className="p-3">
        <HistoryPanel pipelineId={pipelineId} />
      </div>
    </Panel>
  );
}
