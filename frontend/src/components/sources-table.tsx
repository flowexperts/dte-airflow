import { useState } from "react";
import { useRouter } from "@/lib/nav";
import { CopyId, DataTable, type Column, type DataTableSelection } from "@/components/ui";
import {
  bulkDeleteSources,
  deleteSource,
  type BulkDeleteResult,
  type Source,
} from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { summarizeBulkDelete } from "@/lib/bulk-delete";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";

export function SourcesTable({ rows }: { rows: Source[] }) {
  const router = useRouter();
  const { can } = usePermissions();
  const canDelete = can("source:delete");
  const canEdit = can("source:write");
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const toast = useToast();

  const onDelete = async (id: string) => {
    if (!confirm(`Delete source '${id}'?`)) return;
    setBusy(id);
    try {
      await deleteSource(id);
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "source" }));
    } finally {
      setBusy(null);
    }
  };

  const onBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} source(s)?`)) return;
    setBulkBusy(true);
    try {
      const result: BulkDeleteResult = await bulkDeleteSources(ids);
      toast.success({ title: summarizeBulkDelete("source", result) });
      setSelectedIds(new Set());
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "sources" }));
    } finally {
      setBulkBusy(false);
    }
  };

  const selection: DataTableSelection<Source> | undefined = canDelete
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

  const columns: Column<Source>[] = [
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
      render: (r) => (
        <span className="font-mono text-[11.5px] text-muted">{r.source_type}</span>
      ),
    },
    {
      key: "config",
      header: "Config",
      width: "2fr",
      render: (r) => {
        const c = (r.config ?? {}) as Record<string, string>;
        const label = c.bucket_url ?? c.connection_url ?? c.connection_string ?? "";
        return <span className="font-mono text-[11px] text-subtle truncate">{label}</span>;
      },
    },
    {
      key: "actions",
      header: "",
      width: "100px",
      align: "right",
      render: (r) => canDelete ? (
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
        onRowClick={
          canEdit
            ? (r) => router.push(`/sources/edit?id=${encodeURIComponent(r.id)}`)
            : undefined
        }
        emptyText="No sources yet. Create one to reuse across pipelines."
      />
    </div>
  );
}
