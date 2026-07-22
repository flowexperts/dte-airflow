"use client";

import { use } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Button,
  InlineCode,
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
import { getDestination, getPipeline, getRun, getRunEvents, isTerminal, type Destination, type Pipeline, type Run, type RunEvent } from "@/lib/api";
import { RunOutputPreview } from "@/components/run-output-preview";

type Params = Promise<{ id: string }>;

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

  const pillStatus: "ok" | "running" | "failed" | "pending" =
    data?.status === "completed"
      ? "ok"
      : data?.status === "running"
        ? "running"
        : data?.status === "failed"
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
            <MetricRow>
              <Metric
                label="Rows written"
                value={data.rows_written?.toLocaleString() ?? "—"}
                tone={data.status === "completed" ? "ok" : "default"}
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
                label="Engine"
                value={<span className="text-[18px]">DuckDB</span>}
              />
            </MetricRow>

            {data.status === "failed" && data.error && (
              <Panel>
                <PanelHead label="Error" />
                <pre className="p-4 font-mono text-[12.5px] text-red whitespace-pre-wrap break-words">
                  {data.error}
                </pre>
              </Panel>
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
          </>
        )}
      </div>
    </>
  );
}
