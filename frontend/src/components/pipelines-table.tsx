"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import {
  CopyId,
  DataTable,
  Tag,
  type Column,
  type DataTableSelection,
} from "@/components/ui";
import {
  bulkDeletePipelines,
  deletePipeline,
  listPipelineRuns,
  type BulkDeleteResult,
  type Pipeline,
  type Run,
} from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { summarizeBulkDelete } from "@/lib/bulk-delete";
import {
  RunSparkline,
  RunTone,
  isQualityPipeline,
  pipelineShape,
  relativeTime,
  runOutcome,
} from "./pipeline/helpers";
import { TriggerRunButton } from "./pipeline/trigger";

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
    pipelineId ? ["pipeline-runs", pipelineId] : null,
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

export function PipelinesTable({ rows }: { rows: Pipeline[] }) {
  const router = useRouter();
  const toast = useToast();
  const { can } = usePermissions();
  const canDelete = can("pipeline:delete");

  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [busyDelete, setBusyDelete] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? rows.filter(
        (r) =>
          r.name.toLowerCase().includes(q) || r.id.toLowerCase().includes(q),
      )
    : rows;

  /* Selection is cleared whenever the filter changes. Without this a row you
   * can no longer see stays staged for deletion, and "Delete selected" would
   * quietly take it with the rest. */
  const setFilter = (next: string) => {
    setQuery(next);
    setSelectedIds(new Set());
  };

  const onDelete = async (id: string) => {
    if (!confirm(`Delete pipeline '${id}'? Runs will be deleted too.`)) return;
    setBusyDelete(id);
    try {
      await deletePipeline(id);
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "pipeline" }));
    } finally {
      setBusyDelete(null);
    }
  };

  const onBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} pipeline(s)? Their runs will be deleted too.`))
      return;
    setBulkBusy(true);
    try {
      const result: BulkDeleteResult = await bulkDeletePipelines(ids);
      toast.success({ title: summarizeBulkDelete("pipeline", result) });
      setSelectedIds(new Set());
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "pipelines" }));
    } finally {
      setBulkBusy(false);
    }
  };

  const selection: DataTableSelection<Pipeline> | undefined = canDelete
    ? {
        selectedIds,
        rowId: (r) => r.id,
        onToggle: (id) =>
          setSelectedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
          }),
        // Operates on `filtered`, not `rows` — select-all must never reach
        // past what the filter is showing.
        onToggleAll: () =>
          setSelectedIds((prev) =>
            prev.size === filtered.length
              ? new Set()
              : new Set(filtered.map((r) => r.id)),
          ),
      }
    : undefined;

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
      width: "150px",
      align: "right",
      render: (r) => (
        <span className="flex gap-3 justify-end items-center">
          <TriggerRunButton pipeline={r} />
          {canDelete && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(r.id);
              }}
              disabled={busyDelete === r.id}
              className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-red disabled:opacity-50"
            >
              {busyDelete === r.id ? "…" : "Delete"}
            </button>
          )}
        </span>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <input
        value={query}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter pipelines…"
        className="w-full max-w-sm px-3 py-1.5 rounded-[var(--radius)] border border-border bg-surface text-[13px] text-text placeholder:text-subtle outline-none focus:border-border-2"
      />
      {canDelete && selectedIds.size > 0 && (
        <div className="flex items-center justify-between px-3.5 py-2 border border-border rounded-[var(--radius)] bg-surface-2">
          <span className="font-mono text-[11px] text-muted">
            {selectedIds.size} selected
          </span>
          <button
            type="button"
            onClick={onBulkDelete}
            disabled={bulkBusy}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-red disabled:opacity-50"
          >
            {bulkBusy ? "Deleting…" : "Delete selected"}
          </button>
        </div>
      )}
      <DataTable
        columns={columns}
        rows={filtered}
        selection={selection}
        onRowClick={(r) => router.push(`/pipelines/${encodeURIComponent(r.id)}`)}
        emptyText={q ? `Nothing matches “${query}”.` : "No pipelines yet."}
      />
    </div>
  );
}
