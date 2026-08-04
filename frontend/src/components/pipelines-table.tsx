"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CopyId, DataTable, type Column, type DataTableSelection } from "@/components/ui";
import {
  bulkDeletePipelines,
  deletePipeline,
  triggerPipeline,
  type BulkDeleteResult,
  type Pipeline,
} from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { summarizeBulkDelete } from "@/lib/bulk-delete";

export function PipelinesTable({ rows }: { rows: Pipeline[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [busyDelete, setBusyDelete] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const { can } = usePermissions();
  const canTrigger = can("pipeline:trigger");
  const canDelete = can("pipeline:delete");
  const toast = useToast();

  const runPipeline = async (id: string) => {
    if (!id) {
      toast.error({
        title: "This pipeline can't run",
        message: "It's missing an id — edit or delete it before running.",
      });
      return;
    }
    setBusy(id);
    try {
      const { run_id } = await triggerPipeline(id);
      router.push(`/runs/${encodeURIComponent(run_id)}`);
    } catch (e) {
      toast.error(humanizeError(e, { action: "start", entity: "pipeline" }));
      setBusy(null);
    }
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
    if (!confirm(`Delete ${ids.length} pipeline(s)? Their runs will be deleted too.`)) return;
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
        onToggleAll: () =>
          setSelectedIds((prev) =>
            prev.size === rows.length ? new Set() : new Set(rows.map((r) => r.id)),
          ),
      }
    : undefined;

  const columns: Column<Pipeline>[] = [
    {
      key: "id",
      header: "ID",
      width: "220px",
      render: (r) => <CopyId id={r.id} />,
    },
    {
      key: "name",
      header: "Name",
      width: "2.2fr",
      render: (r) => (
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="size-1.5 rounded-full shrink-0 bg-accent" />
          <span className="font-medium truncate">{r.name}</span>
          <span className="font-mono text-[11px] text-subtle ml-1.5 truncate">
            → {r.output_id ?? ""}
          </span>
        </div>
      ),
    },
    {
      key: "sources",
      header: "Sources",
      width: "100px",
      render: (r) => (
        <span className="font-mono text-[12px] text-muted">
          {r.sources?.length ?? 0}
        </span>
      ),
    },
    {
      key: "steps",
      header: "Steps",
      width: "90px",
      render: (r) => (
        <span className="font-mono text-[12px] text-muted">
          {r.steps?.length ?? 0}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "160px",
      align: "right",
      render: (r) => (
        <span className="flex gap-3 justify-end">
          {canTrigger && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                runPipeline(r.id);
              }}
              disabled={busy === r.id}
              className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h disabled:opacity-50 disabled:pointer-events-none"
            >
              {busy === r.id ? "…" : "▶ Run"}
            </button>
          )}
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
    <div className="flex flex-col gap-2">
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
        rows={rows}
        selection={selection}
        onRowClick={(r) => router.push(`/pipelines/${encodeURIComponent(r.id)}`)}
        emptyText="No pipelines yet. Create your first one."
      />
    </div>
  );
}
