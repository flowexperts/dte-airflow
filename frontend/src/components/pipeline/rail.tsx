"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { Panel, PanelHead, Pill, Tabs, type TabOption } from "@/components/ui";
import { PipelinePreview } from "@/components/pipeline-preview";
import { HistoryPanel } from "@/components/builder/history/HistoryPanel";
import { QualityPanel } from "@/components/run/quality-panel";
import { StatRail, StatRow } from "@/components/run/stat-rail";
import {
  STATUS_LABEL,
  elapsedSeconds,
  qualityTally,
  statusTone,
} from "@/components/run/helpers";
import {
  getRun,
  getRunQuality,
  isTerminal,
  listPipelineRuns,
  type Pipeline,
  type QualityCheckResult,
  type Run,
} from "@/lib/api";
import { RunTone, relativeTime, runOutcome } from "./helpers";

type RailTab = "preview" | "runs" | "history";

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
  }>(
    quality && isTerminal(run?.status) ? ["run-quality", runId] : null,
    () => getRunQuality(runId),
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
                {...(tally.total > 0 ? { tone: bad > 0 ? ("warn" as const) : ("ok" as const) } : {})}
              />
            ) : (
              <StatRow
                label="Rows written"
                value={run.rows_written?.toLocaleString() ?? "—"}
              />
            )}
            <StatRow
              label="Elapsed"
              value={elapsedSeconds(run.started_at, run.finished_at)}
            />
          </StatRail>

          {run.error && (
            <div className="px-4 py-3 border-t border-border font-mono text-[12px] text-red whitespace-pre-wrap break-words">
              {run.error}
            </div>
          )}

          {quality && results.length > 0 && (
            <div className="border-t border-border">
              <QualityPanel
                results={results}
                totalRows={null}
                failedCount={bad}
              />
            </div>
          )}

          <div className="px-4 py-2.5 border-t border-border">
            <Link
              href={`/runs/${encodeURIComponent(runId)}`}
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

function RecentRuns({
  pipelineId,
  quality,
}: {
  pipelineId: string;
  quality: boolean;
}) {
  const { data: runs = [] } = useSWR<Run[]>(
    ["pipeline-runs", pipelineId],
    () => listPipelineRuns(pipelineId, 8),
    {
      refreshInterval: (latest) =>
        latest?.some((r) => r.status === "running" || r.status === "pending")
          ? 3000
          : 0,
    },
  );

  return (
    <>
      {runs.length === 0 ? (
        <div className="px-4 py-4 text-sm text-subtle">Never run.</div>
      ) : (
        runs.map((r) => (
          <Link
            key={r.id}
            href={`/runs/${encodeURIComponent(r.id)}`}
            className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-border last:border-b-0 no-underline hover:bg-hover transition-colors"
          >
            <RunTone run={r}>
              <span className="text-[12.5px]">{runOutcome(r, quality)}</span>
            </RunTone>
            <span className="font-mono text-[10.5px] text-subtle shrink-0">
              {relativeTime(r.finished_at ?? r.started_at)}
            </span>
          </Link>
        ))
      )}
    </>
  );
}

/**
 * Right-hand rail: what's running now, what the data looks like, what happened
 * before, and how the spec got here.
 *
 * Tabbed rather than stacked. Four panels in one column meant scrolling to
 * reach history, and each got only a fraction of an already narrow rail — but
 * these are things you consult at different moments, not read together, so
 * showing one at a time costs nothing and gives each the full width.
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
  const [tab, setTab] = useState<RailTab>(showPreview ? "preview" : "runs");

  const tabs: TabOption<RailTab>[] = [
    ...(showPreview ? [{ value: "preview" as const, label: "Preview" }] : []),
    { value: "runs" as const, label: "Runs" },
    { value: "history" as const, label: "History" },
  ];

  return (
    <div className="space-y-5">
      {/* The live run stays pinned above the tabs — it's the one thing you
          want in view regardless of what else you're looking at. */}
      {activeRunId && (
        <LiveRun
          runId={activeRunId}
          quality={quality}
          onDismiss={onDismissRun}
        />
      )}

      <Panel>
        <Tabs options={tabs} value={tab} onChange={setTab} />
        {tab === "preview" && showPreview && (
          <div className="p-3">
            <PipelinePreview pipelineId={pipeline} />
          </div>
        )}
        {tab === "runs" && (
          <RecentRuns pipelineId={pipeline.id} quality={quality} />
        )}
        {tab === "history" && (
          <div className="p-1.5">
            <HistoryPanel pipelineId={pipeline.id} />
          </div>
        )}
      </Panel>
    </div>
  );
}
