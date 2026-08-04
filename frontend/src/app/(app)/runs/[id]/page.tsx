"use client";

import { use } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Button,
  ErrorPanel,
  InlineCode,
  KV,
  KVItem,
  MetricRow,
  Metric,
  PageHeader,
  Panel,
  PanelHead,
  Pill,
  SectionHead,
  Timeline,
  TimelineRow,
  Topbar,
} from "@/components/ui";
import { getDestination, getPipeline, getRun, getRunEvents, getRunQuality, isTerminal, type Destination, type Pipeline, type QualityCheckResult, type Run, type RunEvent } from "@/lib/api";
import { RunOutputPreview } from "@/components/run-output-preview";
import { humanizeCompilerError } from "@/lib/errors";

type Params = Promise<{ id: string }>;

const severityTone: Record<"ok" | "warn" | "err", string> = {
  ok: "var(--green)",
  warn: "var(--gold)",
  err: "var(--red)",
};

function QualityCheckRow({ result }: { result: QualityCheckResult }) {
  const tone: "ok" | "warn" | "err" = result.passed
    ? "ok"
    : result.severity === "warn"
      ? "warn"
      : "err";

  return (
    <div className="relative pl-4 pr-3.5 py-3 border-b border-border last:border-b-0">
      <span
        className="absolute left-0 top-0 bottom-0 w-[3px]"
        style={{ background: severityTone[tone] }}
      />
      <div className="flex items-center gap-2.5 flex-wrap">
        <span className="text-[13px] text-text font-medium">
          {result.label ?? result.contract_type}
        </span>
        <span className="font-mono text-[11px] text-subtle">
          {result.contract_id.slice(0, 8)}
        </span>
        <Pill status={result.passed ? "ok" : result.severity === "warn" ? "warn" : "failed"}>
          {result.passed ? "Passed" : result.severity === "warn" ? "Warning" : "Failed"}
        </Pill>
      </div>
      <div className="font-mono text-[11.5px] text-subtle mt-1">
        {result.detail ?? (result.passed ? "All rows passed" : "—")}
      </div>
    </div>
  );
}

function QualityCheckList({ results }: { results: QualityCheckResult[] }) {
  return (
    <Timeline>
      {results.map((r) => (
        <QualityCheckRow key={r.contract_id} result={r} />
      ))}
    </Timeline>
  );
}

function WarningBanner({ quality }: { quality: Run["quality"] }) {
  return (
    <Panel>
      <PanelHead label="Warning" />
      <div className="px-3.5 py-3 font-mono text-[12.5px]" style={{ color: "var(--gold)" }}>
        Run completed with quality warnings.
        {quality && quality.failed === 0 && quality.warned > 0 && (
          <span className="text-subtle">
            {" "}
            {quality.warned} check{quality.warned === 1 ? "" : "s"} passed with warnings.
          </span>
        )}
      </div>
    </Panel>
  );
}

function elapsedSeconds(started?: string | null, finished?: string | null): string {
  if (!started) return "—";
  const s = new Date(started).getTime();
  const e = finished ? new Date(finished).getTime() : Date.now();
  const ms = Math.max(0, e - s);
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export default function RunDetail({ params }: { params: Params }) {
  const { id } = use(params);

  const { data, error, isLoading } = useSWR<Run>(
    ["run", id],
    () => getRun(id),
    {
      refreshInterval: (latest) => (isTerminal(latest?.status) ? 0 : 2000),
    },
  );

  const { data: pipeline } = useSWR<Pipeline>(
    data?.pipeline_id ? ["pipeline", data.pipeline_id] : null,
    () => getPipeline(data!.pipeline_id),
  );
  const { data: destination } = useSWR<Destination>(
    pipeline?.output_id ? ["destination", pipeline.output_id] : null,
    () => getDestination(pipeline!.output_id),
  );
  const { data: eventsResp } = useSWR<{ events: RunEvent[]; count: number }>(
    ["run-events", id],
    () => getRunEvents(id),
    { refreshInterval: (l) => (isTerminal(data?.status) && l?.count ? 0 : 2000) },
  );
  const events = eventsResp?.events ?? [];

  const { data: qualityResp } = useSWR<{ results: QualityCheckResult[]; count: number }>(
    isTerminal(data?.status) ? ["run-quality", id] : null,
    () => getRunQuality(id),
  );
  const qualityResults = qualityResp?.results ?? [];

  const pillStatus: "ok" | "running" | "failed" | "pending" =
    data?.status === "completed" || data?.status === "completed_with_warnings"
      ? "ok"
      : data?.status === "running"
        ? "running"
        : data?.status === "failed" || data?.status === "failed_quality"
          ? "failed"
          : "pending";

  return (
    <>
      <Topbar
        crumbs={[
          { label: "Workspace", href: "/" },
          { label: "Runs" },
          { label: id.slice(0, 8) },
        ]}
        actions={
          data?.pipeline_id ? (
            <Link href={`/pipelines/${encodeURIComponent(data.pipeline_id)}`}>
              <Button size="sm">Back to pipeline</Button>
            </Link>
          ) : null
        }
      />
      <PageHeader
        title={<>Run <span className="font-mono text-[18px] text-subtle">{id.slice(0, 8)}</span></>}
        sub={data?.pipeline_id}
        actions={data ? <Pill status={pillStatus} /> : null}
      />

      <div className="px-14 py-8 space-y-8">
        {error ? (
          <div className="p-4 border border-red rounded bg-code-bg text-red font-mono text-sm">
            Run not found or backend unreachable: {String(error)}
          </div>
        ) : isLoading || !data ? (
          <div className="text-subtle font-mono text-sm">Loading…</div>
        ) : (
          <>
            {(data.status === "failed" || data.status === "failed_quality") && data.error && (() => {
              const title = data.status === "failed_quality"
                ? "Quality checks failed"
                : undefined;
              const h = humanizeCompilerError(data.error);
              return h ? (
                <ErrorPanel
                  title={title ?? h.title}
                  message={h.message}
                  detail={h.detail}
                />
              ) : (
                <ErrorPanel
                  title={title ?? "Run failed"}
                  message={data.error}
                  detail={null}
                />
              );
            })()}

            {data.status === "completed_with_warnings" && (
              <WarningBanner quality={data.quality} />
            )}

            <MetricRow className="lg:grid-cols-3">
              <Metric
                label="Rows written"
                value={data.rows_written?.toLocaleString() ?? "—"}
                tone={
                  data.status === "completed" ||
                  data.status === "completed_with_warnings"
                    ? "ok"
                    : "default"
                }
              />
              <Metric
                label="Elapsed"
                value={elapsedSeconds(data.started_at, data.finished_at)}
              />
              <Metric
                label="Started"
                value={
                  data.started_at ? (
                    <span className="text-[18px]">
                      {new Date(data.started_at).toLocaleString()}
                    </span>
                  ) : (
                    "—"
                  )
                }
              />
            </MetricRow>

            {qualityResults.length > 0 && (
              <section>
                <SectionHead title="Quality checks" count={qualityResults.length} />
                <QualityCheckList results={qualityResults} />
              </section>
            )}

            {data.params?.params && Object.keys(data.params.params).length > 0 && (
              <Panel>
                <PanelHead
                  label="Trigger params"
                  count={Object.keys(data.params.params).length}
                />
                <KV>
                  {Object.entries(data.params.params).map(([k, v]) => (
                    <KVItem key={k} label={k} value={<InlineCode>{v}</InlineCode>} />
                  ))}
                </KV>
              </Panel>
            )}

            {data.revision_id && data.pipeline_id && (
              <div className="text-[12px] text-subtle font-mono">
                Compiled from revision{" "}
                <Link
                  href={`/pipelines/${encodeURIComponent(data.pipeline_id)}`}
                  className="text-accent hover:underline"
                >
                  {data.revision_id.slice(0, 8)}
                </Link>
              </div>
            )}

            <RunOutputPreview
              runId={id}
              outputType={destination?.config?.type}
              disabled={data.status !== "completed"}
            />

            <details className="group">
              <summary className="cursor-pointer select-none font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle hover:text-text list-none flex items-center gap-2 py-1">
                <span className="text-[10px] text-muted group-open:rotate-90 transition-transform inline-block">▶</span>
                Diagnostics
              </summary>
              <div className="mt-4 space-y-8">
                <section>
                  <SectionHead
                    title="Execution timeline"
                    count="· per-step events"
                  />
                  <Timeline>
                    {events.length === 0 ? (
                      <div className="px-4 py-6 text-center text-subtle text-sm">
                        No events yet.
                      </div>
                    ) : (
                      events.map((e) => {
                        const started = e.started_at ? new Date(e.started_at) : null;
                        const finished = e.finished_at ? new Date(e.finished_at) : null;
                        const dur =
                          started && finished
                            ? `${Math.max(0, finished.getTime() - started.getTime())}ms`
                            : e.status === "started"
                              ? "…"
                              : "—";
                        const tone: "default" | "warn" | "err" =
                          e.status === "failed"
                            ? "err"
                            : e.status === "started"
                              ? "warn"
                              : "default";
                        return (
                          <TimelineRow
                            key={e.step_index}
                            time={started ? started.toLocaleTimeString() : "—"}
                            message={
                              <>
                                step {e.step_index} <InlineCode>{e.op}</InlineCode>{" "}
                                {e.status}
                                {e.message ? ` — ${e.message}` : ""}
                              </>
                            }
                            duration={dur}
                            tone={tone}
                          />
                        );
                      })
                    )}
                  </Timeline>
                </section>

                {data.sql_query && (
                  (() => {
                    const sq = data.sql_query;
                    const stepEntries = sq.step_sqls ? Object.entries(sq.step_sqls) : [];
                    const hasSql = stepEntries.length > 0 || !!sq.final_sql;
                    if (!hasSql) return null;
                    return (
                      <section>
                        <SectionHead
                          title="Compiled SQL"
                          count={stepEntries.length + (sq.final_sql ? 1 : 0)}
                        />
                        <div className="space-y-3">
                          {stepEntries.map(([idx, sql]) => (
                            <details key={idx} className="group">
                              <summary className="cursor-pointer select-none font-mono text-[12px] text-subtle hover:text-text list-none flex items-center gap-2 py-1">
                                <span className="text-[10px] text-muted group-open:rotate-90 transition-transform inline-block">▶</span>
                                Step {idx}
                              </summary>
                              <div className="mt-2 rounded overflow-hidden">
                                <div className="bg-code-bg overflow-y-auto" style={{ maxHeight: "320px" }}>
                                  <pre className="p-3 font-mono text-[12px] text-text whitespace-pre overflow-x-auto">{sql}</pre>
                                </div>
                              </div>
                            </details>
                          ))}
                          {sq.final_sql && (
                            <details className="group" open>
                              <summary className="cursor-pointer select-none font-mono text-[12px] text-subtle hover:text-text list-none flex items-center gap-2 py-1">
                                <span className="text-[10px] text-muted group-open:rotate-90 transition-transform inline-block">▶</span>
                                Final query
                              </summary>
                              <div className="mt-2 rounded overflow-hidden">
                                <div className="bg-code-bg overflow-y-auto" style={{ maxHeight: "320px" }}>
                                  <pre className="p-3 font-mono text-[12px] text-text whitespace-pre overflow-x-auto">{sq.final_sql}</pre>
                                </div>
                              </div>
                            </details>
                          )}
                        </div>
                      </section>
                    );
                  })()
                )}
              </div>
            </details>
          </>
        )}
      </div>
    </>
  );
}
