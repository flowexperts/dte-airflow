import { useState } from "react";
import { useRouter } from "@/lib/nav";
import { CopyId, DataTable, type Column, type DataTableSelection } from "@/components/ui";
import {
  bulkDeleteDestinations,
  deleteDestination,
  type BulkDeleteResult,
  type Destination,
} from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { summarizeBulkDelete } from "@/lib/bulk-delete";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";

export function DestinationsTable({ rows }: { rows: Destination[] }) {
  const router = useRouter();
  const { can } = usePermissions();
  const canDelete = can("destination:delete");
  const canEdit = can("destination:write");
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const toast = useToast();

  const onDelete = async (id: string) => {
    if (!confirm(`Delete destination '${id}'?`)) return;
    setBusy(id);
    try {
      await deleteDestination(id);
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "destination" }));
    } finally {
      setBusy(null);
    }
  };

  const onBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} destination(s)?`)) return;
    setBulkBusy(true);
    try {
      const result: BulkDeleteResult = await bulkDeleteDestinations(ids);
      toast.success({ title: summarizeBulkDelete("destination", result) });
      setSelectedIds(new Set());
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "destinations" }));
    } finally {
      setBulkBusy(false);
    }
  };

  const selection: DataTableSelection<Destination> | undefined = canDelete
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

  const columns: Column<Destination>[] = [
    {
      key: "id",
      header: "ID",
      width: "1.5fr",
      render: (r) => <CopyId id={r.id} />,
    },
    {
      key: "type",
      header: "Type",
      width: "140px",
      render: (r) => <span className="font-mono text-[11.5px] text-muted">{r.config.type}</span>,
    },
    {
      key: "path",
      header: "Path / target",
      width: "2fr",
      render: (r) => {
        const c = r.config as Record<string, string>;
        const label = c.path ?? c.bucket_url ?? c.table ?? "";
        return <span className="font-mono text-[11px] text-subtle truncate">{label}</span>;
      },
    },
    {
      key: "actions",
      header: "",
      width: "100px",
      align: "right",
      render: (r) =>
        canDelete ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(r.id);
            }}
            disabled={busy === r.id}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-red disabled:opacity-50"
          >
            {busy === r.id ? "…" : "Delete"}
          </button>
        ) : null,
    },
  ];

  return (
    <div className="flex flex-col gap-2">
      {canDelete && selectedIds.size > 0 && (
        <div className="flex items-center justify-between px-3.5 py-2 border border-border rounded-[var(--radius)] bg-surface-2">
          <span className="font-mono text-[11px] text-muted">{selectedIds.size} selected</span>
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
        onRowClick={
          canEdit
            ? (r) => router.push(`/destinations/edit?id=${encodeURIComponent(r.id)}`)
            : undefined
        }
        emptyText="No destinations yet. Create one to reuse across pipelines."
      />
    </div>
  );
}
