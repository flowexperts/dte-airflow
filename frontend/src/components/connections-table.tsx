"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CopyId, DataTable, Pill, type Column, type DataTableSelection } from "@/components/ui";
import {
  bulkDeleteConnections,
  deleteConnection,
  testConnection,
  type BulkDeleteResult,
  type Connection,
  type ProbeResult,
} from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { summarizeBulkDelete } from "@/lib/bulk-delete";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";

export function ConnectionsTable({ rows }: { rows: Connection[] }) {
  const router = useRouter();
  const { can } = usePermissions();
  const canDelete = can("connection:delete");
  const canTest = can("connection:test");
  const canEdit = can("connection:write");
  const [busyDelete, setBusyDelete] = useState<string | null>(null);
  const [busyTest, setBusyTest] = useState<string | null>(null);
  const [probes, setProbes] = useState<Record<string, ProbeResult>>({});
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const toast = useToast();

  const onDelete = async (id: string) => {
    if (!confirm(`Delete connection '${id}'?`)) return;
    setBusyDelete(id);
    try {
      await deleteConnection(id);
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "connection" }));
    } finally {
      setBusyDelete(null);
    }
  };

  const onTest = async (id: string) => {
    setBusyTest(id);
    try {
      const p = await testConnection(id);
      setProbes((prev) => ({ ...prev, [id]: p }));
      if (p.ok) {
        toast.success({ title: `Connected to ${id}`, message: `Reachable in ${p.elapsed_ms}ms.` });
      } else {
        toast.error({
          title: `Couldn't connect to ${id}`,
          message: "The credentials or endpoint didn't work.",
          detail: p.detail,
        });
      }
    } catch (e) {
      const human = humanizeError(e, { action: "test", entity: "connection" });
      setProbes((prev) => ({
        ...prev,
        [id]: { ok: false, elapsed_ms: 0, detail: human.message },
      }));
      toast.error(human);
    } finally {
      setBusyTest(null);
    }
  };

  const onBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} connection(s)?`)) return;
    setBulkBusy(true);
    try {
      const result: BulkDeleteResult = await bulkDeleteConnections(ids);
      toast.success({ title: summarizeBulkDelete("connection", result) });
      setSelectedIds(new Set());
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "connections" }));
    } finally {
      setBulkBusy(false);
    }
  };

  const selection: DataTableSelection<Connection> | undefined = canDelete
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

  const columns: Column<Connection>[] = [
    {
      key: "id",
      header: "ID",
      width: "200px",
      render: (r) => <CopyId id={r.id} />,
    },
    {
      key: "name",
      header: "Name",
      width: "1.5fr",
      render: (r) => <span className="text-[13px] truncate">{r.name ?? r.id}</span>,
    },
    {
      key: "type",
      header: "Type",
      width: "140px",
      render: (r) => (
        <span className="font-mono text-[11.5px] text-muted">{r.connection_type}</span>
      ),
    },
    {
      key: "probe",
      header: "Status",
      width: "220px",
      render: (r) => {
        const p = probes[r.id];
        if (!p) return <span className="font-mono text-[11px] text-subtle">—</span>;
        return (
          <span className="flex items-center gap-2 font-mono text-[11px]">
            <Pill status={p.ok ? "ok" : "failed"}>
              {p.ok ? "ok" : "failed"}
            </Pill>
            <span className="text-subtle truncate">{p.detail}</span>
          </span>
        );
      },
    },
    {
      key: "actions",
      header: "",
      width: "160px",
      align: "right",
      render: (r) => (
        <span className="flex gap-3 justify-end">
          {canTest && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onTest(r.id); }}
              disabled={busyTest === r.id}
              className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h disabled:opacity-50"
            >
              {busyTest === r.id ? "…" : "Test"}
            </button>
          )}
          {canDelete && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDelete(r.id); }}
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
        onRowClick={
          canEdit
            ? (r) => router.push(`/connections/${encodeURIComponent(r.id)}/edit`)
            : undefined
        }
        emptyText="No connections yet. Create one to store credentials."
      />
    </div>
  );
}
