"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { CopyId, DataTable, Tag, type Column } from "@/components/ui";
import { listPipelineRuns, type Pipeline, type Run } from "@/lib/api";
import {
  RunSparkline,
  RunTone,
  isQualityPipeline,
  pipelineShape,
  relativeTime,
  runOutcome,
} from "../_lib";
import { LabTriggerButton } from "../_trigger";

/**
 * Per-row run history.
 *
 * This is N requests for N rows — deliberately. The list response carries no
 * run summary today, and feeling the cost here is what tells us whether it's
 * worth adding one server-side. Runs that are still going get polled; finished
 * ones settle and stop.
 */
function useLastRuns(pipelineId: string) {
  const { data } = useSWR<Run[]>(
    pipelineId ? ["lab-runs", pipelineId] : null,
    () => listPipelineRuns(pipelineId, 5),
    {
      refreshInterval: (latest) =>
        latest?.some((r) => r.status === "running" || r.status === "pending")
          ? 3000
          : 0,
      revalidateOnFocus: false,
    },
  );
  return data ?? [];
}

function LastRunCell({ pipeline }: { pipeline: Pipeline }) {
  const runs = useLastRuns(pipeline.id);
  const latest = runs[0];
  const quality = isQualityPipeline(pipeline);

  if (runs.length === 0) {
    return <span className="text-[12.5px] text-subtle">never run</span>;
  }

  return (
    <div className="min-w-0">
      <RunTone run={latest}>
        <span className="text-[12.5px]">{runOutcome(latest, quality)}</span>
      </RunTone>
      <div className="flex items-center gap-2 mt-1">
        <RunSparkline runs={runs} />
        <span className="font-mono text-[10.5px] text-subtle">
          {relativeTime(latest?.finished_at ?? latest?.started_at)}
        </span>
      </div>
    </div>
  );
}

export function LabHealthTable({ rows }: { rows: Pipeline[] }) {
  const router = useRouter();
  const [query, setQuery] = useState("");

  const q = query.trim().toLowerCase();
  const filtered = q
    ? rows.filter(
        (r) =>
          r.name.toLowerCase().includes(q) || r.id.toLowerCase().includes(q),
      )
    : rows;

  const columns: Column<Pipeline>[] = [
    {
      key: "name",
      header: "Pipeline",
      width: "2.4fr",
      render: (r) => (
        <div className="min-w-0">
          <div className="font-medium truncate">{r.name}</div>
          <div className="mt-0.5">
            <CopyId id={r.id} />
          </div>
        </div>
      ),
    },
    {
      key: "type",
      header: "Type",
      width: "110px",
      render: (r) =>
        isQualityPipeline(r) ? (
          <Tag variant="output">quality</Tag>
        ) : (
          <Tag>transform</Tag>
        ),
    },
    {
      key: "last_run",
      header: "Last run",
      width: "1.3fr",
      render: (r) => <LastRunCell pipeline={r} />,
    },
    {
      key: "shape",
      header: "Shape",
      width: "1fr",
      render: (r) => (
        <span className="font-mono text-[11.5px] text-muted">
          {pipelineShape(r)}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "90px",
      align: "right",
      render: (r) => <LabTriggerButton pipeline={r} />,
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter pipelines…"
        className="w-full max-w-sm px-3 py-1.5 rounded-[var(--radius)] border border-border bg-surface text-[13px] text-text placeholder:text-subtle outline-none focus:border-border-2"
      />
      <DataTable
        columns={columns}
        rows={filtered}
        onRowClick={(r) => router.push(`/lab/pipelines/${encodeURIComponent(r.id)}`)}
        emptyText={q ? `Nothing matches “${query}”.` : "No pipelines yet."}
      />
    </div>
  );
}
