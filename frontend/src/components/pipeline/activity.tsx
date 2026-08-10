"use client";

import { useState } from "react";
import useSWR from "swr";
import { Pagination, Panel } from "@/components/ui";
import { HistoryPanel } from "@/components/builder/history/HistoryPanel";
import { RunsTable } from "@/components/runs-table";
import { listPipelineRuns, listPipelineRunsPage, type Run } from "@/lib/api";

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

export const RUNS_PAGE_SIZE = 20;

/** Latest runs only — feeds the tab badge, not the table. */
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

export function RunsPane({ pipelineId }: { pipelineId: string }) {
  const [offset, setOffset] = useState(0);

  const { data, isLoading } = useSWR(
    ["pipeline-runs-page", pipelineId, offset],
    () => listPipelineRunsPage(pipelineId, RUNS_PAGE_SIZE, offset),
    {
      // Hold the previous page while the next one loads, so paging doesn't
      // collapse the table to an empty state and bounce the scroll position.
      keepPreviousData: true,
      refreshInterval: (latest) =>
        latest?.items.some((r) => r.status === "running" || r.status === "pending")
          ? 3000
          : 0,
    },
  );

  const runs = data?.items ?? [];
  const total = data?.total ?? 0;

  if (!isLoading && total === 0) {
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
      <Pagination
        total={total}
        limit={RUNS_PAGE_SIZE}
        offset={offset}
        onChange={setOffset}
      />
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
