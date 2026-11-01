import { useState } from "react";
import { Link } from "@/lib/nav";
import useSWR from "swr";
import { Pagination, Panel } from "@/components/ui";
import { listPipelineRevisionsPage, type PipelineRevision } from "@/lib/api";

const REVISIONS_PAGE_SIZE = 20;

/**
 * Revisions newest-first. A row opens the revision, whose page shows the
 * read-only spec beside its YAML and the diff against the revision before
 * it — the list itself carries no diff.
 */
export function HistoryPanel({ pipelineId }: { pipelineId: string }) {
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading } = useSWR(
    ["pipeline-revisions", pipelineId, offset],
    () => listPipelineRevisionsPage(pipelineId, REVISIONS_PAGE_SIZE, offset),
    { keepPreviousData: true },
  );

  if (isLoading) {
    return <div className="text-[12px] text-subtle px-3 py-4">Loading history…</div>;
  }
  if (error) {
    return <div className="text-[12px] text-red px-3 py-4">Couldn&apos;t load history.</div>;
  }
  const revs = data?.items ?? [];
  if (revs.length === 0) {
    return (
      <div className="text-[12px] text-subtle px-3 py-4">
        No revisions yet. Every edit starts recording here.
      </div>
    );
  }

  return (
    <Panel>
      {revs.map((rev) => (
        <RevisionRow key={rev.id} rev={rev} />
      ))}
      <Pagination
        total={data?.total ?? 0}
        limit={REVISIONS_PAGE_SIZE}
        offset={offset}
        onChange={setOffset}
      />
    </Panel>
  );
}

function RevisionRow({ rev }: { rev: PipelineRevision }) {
  const when = rev.changed_at ? new Date(rev.changed_at).toLocaleString() : "unknown";
  return (
    <Link
      href={`/pipelines/revision?id=${encodeURIComponent(rev.pipeline_id)}&rev=${encodeURIComponent(rev.id)}`}
      className="grid grid-cols-[auto_1fr_auto] gap-3 items-center px-3.5 py-3 border-b border-border last:border-b-0 hover:bg-hover transition-colors"
    >
      <span className="font-mono text-[10.5px] text-subtle">{rev.id.slice(0, 8)}</span>
      <div className="min-w-0">
        <div className="text-[13px]">{rev.summary ?? "(initial revision)"}</div>
        <div className="font-mono text-[11px] text-subtle mt-0.5">
          {when} · {rev.changed_by ?? "system"}
        </div>
      </div>
      <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">View</span>
    </Link>
  );
}
