import { useState } from "react";
import { Link } from "@/lib/nav";
import useSWR from "swr";
import { Button, Pagination, Panel, Tag } from "@/components/ui";
import { listPipelineRevisionsPage, type PipelineRevision } from "@/lib/api";
import { DiffView } from "./DiffView";

const REVISIONS_PAGE_SIZE = 20;

/**
 * Lists revisions newest-first, lets the user pin two to diff. Selection
 * model: click a row to toggle it in a set of at most two. When two are
 * selected we render <DiffView> against the pair.
 *
 * SWR key is stable per pipeline; the fetcher runs the typed client
 * helper so PipelineRevision[] flows through with no cast.
 */
export function HistoryPanel({ pipelineId }: { pipelineId: string }) {
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading } = useSWR(
    ["pipeline-revisions", pipelineId, offset],
    () => listPipelineRevisionsPage(pipelineId, REVISIONS_PAGE_SIZE, offset),
    { keepPreviousData: true },
  );
  const [selected, setSelected] = useState<string[]>([]);

  if (isLoading) {
    return <div className="text-[12px] text-subtle px-3 py-4">Loading history…</div>;
  }
  if (error) {
    return (
      <div className="text-[12px] text-red px-3 py-4">
        Couldn&apos;t load history.
      </div>
    );
  }
  const revs = data?.items ?? [];
  const total = data?.total ?? 0;
  if (revs.length === 0) {
    return (
      <div className="text-[12px] text-subtle px-3 py-4">
        No revisions yet. Every edit starts recording here.
      </div>
    );
  }

  const toggle = (id: string) => {
    setSelected((s) => {
      if (s.includes(id)) return s.filter((x) => x !== id);
      if (s.length >= 2) return [s[1]!, id]; // FIFO: drop the oldest pin
      return [...s, id];
    });
  };
  const clear = () => setSelected([]);

  // Diff order: older → newer (list is newest-first, so from = later index).
  const [a, b] = selected;
  const older = a && b
    ? (revs.findIndex((r) => r.id === a) > revs.findIndex((r) => r.id === b) ? a : b)
    : null;
  const newer = a && b ? (older === a ? b : a) : null;

  return (
    <div className="space-y-4">
      <Panel>
        {revs.map((rev) => (
          <RevisionRow
            key={rev.id}
            rev={rev}
            selected={selected.includes(rev.id)}
            onToggle={() => toggle(rev.id)}
          />
        ))}
        <Pagination
          total={total}
          limit={REVISIONS_PAGE_SIZE}
          offset={offset}
          onChange={setOffset}
        />
      </Panel>
      {selected.length > 0 && (
        <div className="flex items-center gap-3 text-[12px] text-subtle">
          <span>{selected.length}/2 selected for diff</span>
          <Button size="sm" variant="ghost" onClick={clear}>Clear</Button>
        </div>
      )}
      {older && newer && (
        <DiffView pipelineId={pipelineId} fromId={older} toId={newer} />
      )}
    </div>
  );
}

/**
 * Two actions per row, so it can't be one big button.
 *
 * Selecting for a diff and opening the revision are different intents —
 * "compare these two" versus "show me this one". The row body toggles the
 * diff pin; "View" opens the read-only canvas. A `<Link>` nested inside a
 * `<button>` is invalid HTML and swallows the click, so the toggle is its own
 * element sitting beside the link rather than wrapping it.
 */
function RevisionRow({
  rev,
  selected,
  onToggle,
}: {
  rev: PipelineRevision;
  selected: boolean;
  onToggle: () => void;
}) {
  const when = rev.changed_at ? new Date(rev.changed_at).toLocaleString() : "unknown";
  const who = rev.changed_by ?? "system";
  const short = rev.id.slice(0, 8);
  return (
    <div
      className={
        "grid grid-cols-[1fr_auto] gap-3 items-center border-b border-border last:border-b-0 hover:bg-hover transition-colors " +
        (selected ? "bg-[color:var(--accent-tint)]" : "")
      }
    >
      <button
        type="button"
        onClick={onToggle}
        className="text-left grid grid-cols-[auto_1fr] gap-3 items-center px-3.5 py-3 min-w-0"
      >
        <span className="font-mono text-[10.5px] text-subtle">{short}</span>
        <div className="min-w-0">
          <div className="text-[13px]">{rev.summary ?? "(initial revision)"}</div>
          <div className="font-mono text-[11px] text-subtle mt-0.5">
            {when} · {who}
          </div>
        </div>
      </button>
      <div className="flex items-center gap-2 pr-3.5">
        {selected && <Tag>selected</Tag>}
        <Link
          href={`/pipelines/revision?id=${encodeURIComponent(rev.pipeline_id)}&rev=${encodeURIComponent(rev.id)}`}
          className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-accent"
        >
          View
        </Link>
      </div>
    </div>
  );
}
