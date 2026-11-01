import useSWR from "swr";
import { Panel } from "@/components/ui";
import { HistoryPanel } from "@/components/builder/history/HistoryPanel";
import { RunsTable } from "@/components/runs-table";
import { airflowDagHref } from "@/components/run/helpers";
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

export const RECENT_RUNS = 20;

function useRecentRuns(pipelineId: string) {
  return useSWR<Run[]>(
    ["pipeline-runs", pipelineId],
    () => listPipelineRuns(pipelineId, RECENT_RUNS),
    {
      refreshInterval: (latest) =>
        latest?.some((r) => r.status === "running" || r.status === "pending") ? 3000 : 0,
    },
  );
}

/** Latest runs only — feeds the tab badge, not the table. */
export function usePipelineRuns(pipelineId: string) {
  return useRecentRuns(pipelineId).data ?? [];
}

/** The last few runs only. Full history, filtering and retries are Airflow's
 *  grid (plan 087), one link away; a second pager here would only drift. */
export function RunsPane({ pipelineId }: { pipelineId: string }) {
  const { data, isLoading } = useRecentRuns(pipelineId);
  const runs = data ?? [];

  if (!isLoading && runs.length === 0) {
    return (
      <Panel>
        <div className="px-4 py-16 text-center text-sm text-subtle">
          Never run. Trigger it from the header to see results here.
        </div>
      </Panel>
    );
  }

  const dagId = runs[0]?.dag_id;
  return (
    <Panel>
      <div className="p-3">
        <RunsTable runs={runs} />
      </div>
      {dagId && (
        <div className="px-4 py-3 border-t border-border text-[12.5px] text-subtle">
          Last {RECENT_RUNS} runs.{" "}
          <a href={airflowDagHref(dagId)} className="text-accent hover:underline">
            All runs in Airflow →
          </a>
        </div>
      )}
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
