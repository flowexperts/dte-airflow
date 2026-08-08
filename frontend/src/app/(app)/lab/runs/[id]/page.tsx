"use client";

import { use } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  Button,
  ErrorPanel,
  PageHeader,
  Panel,
  PanelHead,
  Pill,
  Topbar,
} from "@/components/ui";
import { RunOutputPreview } from "@/components/run-output-preview";
import { Diagnostics } from "@/components/run/diagnostics";
import { QualityCheckRow } from "@/components/run/quality-panel";
import { StatRail, StatRow } from "@/components/run/stat-rail";
import { VerdictBanner } from "@/components/run/verdict-banner";
import {
  STATUS_LABEL,
  checkTone,
  elapsedSeconds,
  qualityTally,
  statusTone,
  toneVar,
  type Tone,
} from "@/components/run/helpers";
import { stepTitle } from "@/components/builder/steps/summary";
import type { StepShape } from "@/components/builder/steps/types";
import { labelFor } from "@/components/builder/steps/types";
import {
  getDestination,
  getPipeline,
  getRun,
  getRunEvents,
  getRunQuality,
  isTerminal,
  type Destination,
  type Pipeline,
  type QualityCheckResult,
  type Run,
  type RunEvent,
} from "@/lib/api";
import { humanizeCompilerError } from "@/lib/errors";

type Params = Promise<{ id: string }>;

/** Deep link into the step that produced a problem. This edge is what the
 *  current UI is missing — a failed run tells you what broke but not where,
 *  so you navigate back and count step indices by hand. */
function stepHref(pipelineId: string, index: number) {
  return `/lab/pipelines/${encodeURIComponent(pipelineId)}#step-${index}`;
}

function FixLink({
  pipelineId,
  index,
  label,
}: {
  pipelineId: string;
  index: number;
  label: string;
}) {
  return (
    <Link
      href={stepHref(pipelineId, index)}
      className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent no-underline hover:text-accent-h shrink-0"
    >
      {label} →
    </Link>
  );
}

/**
 * Failed steps, lifted out of the diagnostics timeline and given a way back
 * into the editor. Renders nothing when the run had no step-level failure.
 */
function FailedSteps({
  events,
  pipeline,
}: {
  events: RunEvent[];
  pipeline: Pipeline | undefined;
}) {
  const failed = events.filter((e) => e.status === "failed");
  if (failed.length === 0 || !pipeline) return null;
  const steps = (pipeline.steps ?? []) as StepShape[];

  return (
    <Panel>
      <PanelHead label="Where it broke" count={failed.length} />
      {failed.map((e, i) => {
        const idx = e.step_index ?? -1;
        const step = idx >= 0 ? steps[idx] : undefined;
        return (
          <div
            key={`${e.step_index}-${i}`}
            className="grid grid-cols-[3px_1fr] border-b border-border last:border-b-0"
          >
            <span style={{ background: toneVar.err }} />
            <div className="px-4 py-3">
              <div className="flex items-center gap-2.5 flex-wrap">
                <span className="font-mono text-[10px] font-bold tracking-[0.15em] uppercase text-accent px-1.5 py-0.5 rounded-sm bg-[color:var(--accent-tint)]">
                  {step ? labelFor(step) : e.op}
                </span>
                <span className="text-[13.5px] text-text font-medium">
                  {step ? stepTitle(step) : `step ${idx}`}
                </span>
                {idx >= 0 && (
                  <span className="ml-auto">
                    <FixLink
                      pipelineId={pipeline.id}
                      index={idx}
                      label="Fix step"
                    />
                  </span>
                )}
              </div>
              {e.message && (
                <div className="text-[12.5px] text-muted mt-1 font-mono break-words">
                  {e.message}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </Panel>
  );
}

/**
 * Quality checks with a route back to the check that failed. `check` steps
 * carry the label the result reports, so we match on it to find the index.
 */
function QualityChecks({
  results,
  pipeline,
  totalRows,
}: {
  results: QualityCheckResult[];
  pipeline: Pipeline | undefined;
  totalRows: number | null;
}) {
  const steps = ((pipeline?.steps ?? []) as StepShape[]) ?? [];
  const failedCount = results.filter((r) => !r.passed).length;

  const indexForResult = (r: QualityCheckResult): number => {
    const label = r.label;
    if (!label) return -1;
    return steps.findIndex(
      (s) => (s.op === "check" || s.op === "profile") && s.label === label,
    );
  };

  return (
    <Panel>
      <PanelHead
        label="Quality checks"
        count={
          <>
            {results.length} check{results.length === 1 ? "" : "s"}
            {failedCount > 0 && (
              <span className="text-subtle"> · {failedCount} failed</span>
            )}
          </>
        }
      />
      {results.map((r) => {
        const idx = pipeline ? indexForResult(r) : -1;
        return (
          <div key={r.contract_id} className="relative">
            <QualityCheckRow result={r} totalRows={totalRows} />
            {!r.passed && idx >= 0 && pipeline && (
              <div className="absolute right-4 bottom-3">
                <FixLink pipelineId={pipeline.id} index={idx} label="Edit check" />
              </div>
            )}
          </div>
        );
      })}
    </Panel>
  );
}

export default function LabRunDetail({ params }: { params: Params }) {
  const { id } = use(params);

  const { data: run, error } = useSWR<Run>(["lab-run", id], () => getRun(id), {
    refreshInterval: (latest) => (isTerminal(latest?.status) ? 0 : 2000),
  });

  const { data: pipeline } = useSWR<Pipeline>(
    run?.pipeline_id ? ["pipeline", run.pipeline_id] : null,
    () => getPipeline(run!.pipeline_id),
  );
  const { data: destination } = useSWR<Destination>(
    pipeline?.output_id ? ["destination", pipeline.output_id] : null,
    () => getDestination(pipeline!.output_id),
  );
  const { data: eventsResp } = useSWR<{ events: RunEvent[]; count: number }>(
    ["lab-run-events", id],
    () => getRunEvents(id),
    { refreshInterval: (l) => (isTerminal(run?.status) && l?.count ? 0 : 2000) },
  );
  const events = eventsResp?.events ?? [];

  const { data: qualityResp } = useSWR<{
    results: QualityCheckResult[];
    count: number;
  }>(isTerminal(run?.status) ? ["lab-run-quality", id] : null, () =>
    getRunQuality(id),
  );
  const results = qualityResp?.results ?? [];

  const quality = pipeline?.pipeline_type === "quality";
  const tone = statusTone(run?.status);
  const bannerTone: Tone = tone === "pending" ? "warn" : tone;
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
  const rows = run?.rows_written ?? null;
  const firstProblem = results.find((r) => !r.passed);
  const humanized = run?.error ? humanizeCompilerError(run.error) : null;

  const stepSqls = new Map<number, string>(
    Object.entries(run?.sql_query?.step_sqls ?? {}).map(([k, v]) => [
      Number(k),
      v,
    ]),
  );

  return (
    <>
      <Topbar
        crumbs={[
          { label: "Workspace", href: "/" },
          { label: "Lab", href: "/lab" },
          { label: "Runs" },
          { label: id.slice(0, 8) },
        ]}
        actions={
          run?.pipeline_id ? (
            <Link href={`/lab/pipelines/${encodeURIComponent(run.pipeline_id)}`}>
              <Button size="sm">Back to pipeline</Button>
            </Link>
          ) : null
        }
      />
      <PageHeader
        title={
          <>
            Run{" "}
            <span className="font-mono text-[18px] text-subtle">
              {id.slice(0, 8)}
            </span>
          </>
        }
        sub={quality ? "quality" : "transform"}
        lede={pipeline?.name ?? run?.pipeline_id}
        actions={
          run ? <Pill status={pillStatus}>{STATUS_LABEL[run.status]}</Pill> : null
        }
      />

      <div className="px-14 py-8 space-y-5">
        {error ? (
          <ErrorPanel
            title="Run not found"
            message={String(error)}
            detail={null}
          />
        ) : !run ? (
          <div className="text-subtle font-mono text-sm">Loading…</div>
        ) : (
          <>
            {run.error ? (
              <ErrorPanel
                title={
                  run.status === "failed_quality"
                    ? "Quality checks failed"
                    : (humanized?.title ?? "Run failed")
                }
                message={humanized?.message ?? run.error}
                detail={humanized?.detail ?? null}
              />
            ) : (
              isTerminal(run.status) && (
                <VerdictBanner
                  tone={bannerTone}
                  headline={
                    quality ? (
                      bad > 0 ? (
                        <>
                          {bad} of {tally.total} check
                          {tally.total === 1 ? "" : "s"} failed
                          {firstProblem && (
                            <>
                              {" "}
                              — “{firstProblem.label ?? firstProblem.contract_type}”
                            </>
                          )}
                        </>
                      ) : (
                        <>
                          All {tally.total} check{tally.total === 1 ? "" : "s"}{" "}
                          passed
                        </>
                      )
                    ) : (
                      <>
                        Wrote {rows?.toLocaleString() ?? "—"} row
                        {rows === 1 ? "" : "s"}
                        {destination?.config?.type && (
                          <> to {destination.config.type.replace(/_/g, " ")}</>
                        )}
                      </>
                    )
                  }
                  sub={`Finished in ${elapsedSeconds(run.started_at, run.finished_at)}.`}
                />
              )
            )}

            <FailedSteps events={events} pipeline={pipeline} />

            <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-5 items-start">
              <div className="space-y-5 min-w-0">
                {results.length > 0 && (
                  <QualityChecks
                    results={results}
                    pipeline={pipeline}
                    totalRows={quality ? null : rows}
                  />
                )}
                {!quality && (
                  <RunOutputPreview
                    runId={id}
                    outputType={destination?.config?.type}
                    disabled={run.status !== "completed"}
                  />
                )}
              </div>

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
                  <StatRow
                    label="Rows written"
                    value={rows?.toLocaleString() ?? "—"}
                  />
                )}
                <StatRow
                  label="Elapsed"
                  value={elapsedSeconds(run.started_at, run.finished_at)}
                />
                <StatRow
                  label="Started"
                  value={
                    run.started_at
                      ? new Date(run.started_at).toLocaleString()
                      : "—"
                  }
                  small
                />
                <StatRow label="Engine" value="DuckDB" small />
              </StatRail>
            </div>

            <Diagnostics
              events={events}
              stepSqls={quality ? stepSqls : new Map()}
              finalSql={run.sql_query?.final_sql ?? null}
              sqlTabLabel={quality ? "Check SQL" : "Compiled SQL"}
            />
          </>
        )}
      </div>
    </>
  );
}
