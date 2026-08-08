"use client";

import Link from "next/link";
import useSWR from "swr";
import { Panel, SectionHead, Tag } from "@/components/ui";
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

function PipelineCard({ pipeline }: { pipeline: Pipeline }) {
  const { data: runs = [] } = useSWR<Run[]>(
    ["lab-runs", pipeline.id],
    () => listPipelineRuns(pipeline.id, 5),
    {
      refreshInterval: (latest) =>
        latest?.some((r) => r.status === "running" || r.status === "pending")
          ? 3000
          : 0,
      revalidateOnFocus: false,
    },
  );
  const latest = runs[0];
  const quality = isQualityPipeline(pipeline);

  return (
    <Panel className="hover:border-border-2 transition-colors">
      <Link
        href={`/lab/pipelines/${encodeURIComponent(pipeline.id)}`}
        className="block no-underline text-text px-4 py-3.5"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[15px] font-medium truncate">{pipeline.name}</div>
            <div className="font-mono text-[11px] text-subtle truncate mt-0.5">
              {pipeline.id}
            </div>
          </div>
          {quality ? <Tag variant="output">quality</Tag> : <Tag>transform</Tag>}
        </div>

        <div className="mt-3 pt-3 border-t border-border flex items-center justify-between gap-3">
          <RunTone run={latest}>
            <span className="text-[13px]">{runOutcome(latest, quality)}</span>
          </RunTone>
          <span className="font-mono text-[10.5px] text-subtle shrink-0">
            {latest ? relativeTime(latest.finished_at ?? latest.started_at) : "—"}
          </span>
        </div>

        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="font-mono text-[11px] text-muted truncate">
            {pipelineShape(pipeline)}
          </span>
          <RunSparkline runs={runs} />
        </div>
      </Link>
      <div className="px-4 py-2 border-t border-border flex justify-end">
        <LabTriggerButton pipeline={pipeline} />
      </div>
    </Panel>
  );
}

function CardGroup({ title, pipelines }: { title: string; pipelines: Pipeline[] }) {
  return (
    <section>
      <SectionHead title={title} count={`· ${pipelines.length}`} />
      {pipelines.length === 0 ? (
        <Panel>
          <div className="px-4 py-6 text-sm text-subtle text-center">
            None yet.
          </div>
        </Panel>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {pipelines.map((p) => (
            <PipelineCard key={p.id} pipeline={p} />
          ))}
        </div>
      )}
    </section>
  );
}

/** Transform and quality as peer sections — the two types stop being
 *  distinguishable only by which nav item you arrived from. */
export function LabPipelineCards({ rows }: { rows: Pipeline[] }) {
  const transform = rows.filter((p) => !isQualityPipeline(p));
  const quality = rows.filter(isQualityPipeline);

  return (
    <div className="space-y-8">
      <CardGroup title="Transform" pipelines={transform} />
      <CardGroup title="Quality" pipelines={quality} />
    </div>
  );
}
