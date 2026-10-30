import { Link } from "@/lib/nav";
import useSWR from "swr";
import { Panel, PanelHead, Pill } from "@/components/ui";
import { PipelinePreview } from "@/components/pipeline-preview";
import { QualityPanel } from "@/components/run/quality-panel";
import { StatRail, StatRow } from "@/components/run/stat-rail";
import { STATUS_LABEL, elapsedSeconds, qualityTally, statusTone } from "@/components/run/helpers";
import {
  getRun,
  getRunQuality,
  isTerminal,
  type Pipeline,
  type QualityCheckResult,
  type Run,
} from "@/lib/api";

/**
 * The live run, shown where you triggered it.
 *
 * Today triggering pushes you to /runs/{id} and the pipeline you were reading
 * is gone. Here the run reports back in place; the full run page stays one
 * click away for the deep dive.
 */
function LiveRun({
  runId,
  quality,
  onDismiss,
}: {
  runId: string;
  quality: boolean;
  onDismiss: () => void;
}) {
  const { data: run } = useSWR<Run>(["run", runId], () => getRun(runId), {
    refreshInterval: (latest) => (isTerminal(latest?.status) ? 0 : 2000),
  });

  const { data: qualityResp } = useSWR<{
    results: QualityCheckResult[];
    count: number;
  }>(quality && isTerminal(run?.status) ? ["run-quality", runId] : null, () =>
    getRunQuality(runId),
  );
  const results = qualityResp?.results ?? [];

  const tone = statusTone(run?.status);
  const pillStatus =
    tone === "ok"
      ? "ok"
      : tone === "warn"
        ? "warn"
        : tone === "err"
          ? "failed"
          : run?.status === "running"
            ? "running"
            : "pending";

  const tally = qualityTally(results, run?.quality);
  const bad = tally.failed + tally.warned;

  return (
    <Panel>
      <PanelHead
        label="This run"
        count={
          <span className="flex items-center gap-2">
            {run && <Pill status={pillStatus}>{STATUS_LABEL[run.status]}</Pill>}
            <button
              type="button"
              onClick={onDismiss}
              className="text-subtle hover:text-text text-[15px] leading-none"
              aria-label="Dismiss run"
            >
              ×
            </button>
          </span>
        }
      />
      {!run ? (
        <div className="px-4 py-4 text-sm text-subtle">Starting…</div>
      ) : (
        <>
          <StatRail>
            {quality ? (
              <StatRow
                label="Checks passed"
                value={`${tally.passed} / ${tally.total}`}
                {...(tally.total > 0
                  ? { tone: bad > 0 ? ("warn" as const) : ("ok" as const) }
                  : {})}
              />
            ) : (
              <StatRow label="Rows written" value={run.rows_written?.toLocaleString() ?? "—"} />
            )}
            <StatRow label="Elapsed" value={elapsedSeconds(run.started_at, run.finished_at)} />
          </StatRail>

          {run.error && (
            <div className="px-4 py-3 border-t border-border font-mono text-[12px] text-red whitespace-pre-wrap break-words">
              {run.error}
            </div>
          )}

          {quality && results.length > 0 && (
            <div className="border-t border-border">
              <QualityPanel results={results} totalRows={null} failedCount={bad} />
            </div>
          )}

          <div className="px-4 py-2.5 border-t border-border">
            <Link
              href={`/runs/detail?id=${encodeURIComponent(runId)}`}
              className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent no-underline hover:text-accent-h"
            >
              Full run detail →
            </Link>
          </div>
        </>
      )}
    </Panel>
  );
}

/**
 * Right-hand rail: the present tense only.
 *
 * The live run and the preview both describe the spec as it stands right now
 * — the preview re-runs as you type, and the run is the thing you just
 * started. Past runs and revision history live below the canvas in
 * PipelineActivity instead: different time axis, different mode of attention,
 * and they read badly in a rail this narrow (420px at xl, 480px at 2xl).
 */
export function Rail({
  pipeline,
  activeRunId,
  onDismissRun,
  showPreview,
}: {
  pipeline: Pipeline;
  activeRunId: string | null;
  onDismissRun: () => void;
  showPreview: boolean;
}) {
  const quality = pipeline.pipeline_type === "quality";

  return (
    <div className="space-y-5">
      {activeRunId && <LiveRun runId={activeRunId} quality={quality} onDismiss={onDismissRun} />}
      {/* Comparisons moved to a tab beside Spec / Runs / History — past
          comparisons are history of this pipeline, the same kind of thing
          the other tabs hold, and the rail is for what is happening now. */}
      {showPreview && <PipelinePreview pipelineId={pipeline} />}
    </div>
  );
}
