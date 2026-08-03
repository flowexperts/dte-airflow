"use client";

import { use } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Button,
  DataTable,
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
  type Column,
} from "@/components/ui";
import { getDestination, getPipeline, getRun, getRunEvents, getRunQuality, isTerminal, type Destination, type Pipeline, type QualityCheckResult, type Run, type RunEvent } from "@/lib/api";
import { RunOutputPreview } from "@/components/run-output-preview";
import { humanizeCompilerError } from "@/lib/errors";

type Params = Promise<{ id: string }>;

const qualityColumns: Column<QualityCheckResult>[] = [
  {
    key: "contract_type",
    header: "Contract type",
    width: "200px",
    render: (r) => (
      <span className="font-mono text-[12px] text-text">{r.contract_type}</span>
    ),
  },
  {
    key: "contract_id",
    header: "Contract ID",
    width: "130px",
    render: (r) => (
      <span className="font-mono text-[11px] text-subtle">{r.contract_id.slice(0, 8)}</span>
    ),
  },
  {
    key: "status",
    header: "Status",
    width: "120px",
    render: (r) => (
      r.passed ? (
        <Pill status="ok">Passed</Pill>
      ) : r.severity === "warn" ? (
        <Pill status="running">Warning</Pill>
      ) : (
        <Pill status="failed">Failed</Pill>
      )
    ),
  },
  {
    key: "detail",
    header: "Detail",
    width: "1fr",
    render: (r) => (
      <span className="font-mono text-[11.5px] text-subtle">{r.detail ?? ""}</span>
    ),
  },
];

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
            {(() => {
              const q = data.quality;
              const qTotal = q ? q.passed + q.failed + q.warned : 0;
              const qValue = !q || qTotal === 0
                ? "—"
                : `${q.passed}/${qTotal}`;
              const qTone: "ok" | "warn" | "err" | "default" =
                !q || qTotal === 0
                  ? "default"
                  : q.failed > 0
                    ? "err"
                    : q.warned > 0
                      ? "warn"
                      : "ok";
              return (
                <MetricRow>
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
                  <Metric
                    label="Quality checks"
                    value={qValue}
                    tone={qTone}
                  />
                </MetricRow>
              );
            })()}

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
              <div className="p-3 border border-border rounded bg-surface font-mono text-[12.5px] text-gold">
                Run completed with quality warnings.
              </div>
            )}

            <RunOutputPreview
              runId={id}
              outputType={destination?.config?.type}
              disabled={data.status !== "completed"}
            />

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

            {qualityResults.length > 0 && (
              <section>
                <SectionHead title="Quality checks" count={qualityResults.length} />
                <DataTable<QualityCheckResult>
                  columns={qualityColumns}
                  rows={qualityResults}
                />
              </section>
            )}
          </>
        )}
      </div>
    </>
  );
}
