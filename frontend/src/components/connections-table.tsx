"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { DataTable, Pill, type Column } from "@/components/ui";
import { deleteConnection, testConnection, type Connection, type ProbeResult } from "@/lib/api";

export function ConnectionsTable({ rows }: { rows: Connection[] }) {
  const router = useRouter();
  const [busyDelete, setBusyDelete] = useState<string | null>(null);
  const [busyTest, setBusyTest] = useState<string | null>(null);
  const [probes, setProbes] = useState<Record<string, ProbeResult>>({});

  const onDelete = async (id: string) => {
    if (!confirm(`Delete connection '${id}'?`)) return;
    setBusyDelete(id);
    try {
      await deleteConnection(id);
      router.refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyDelete(null);
    }
  };

  const onTest = async (id: string) => {
    setBusyTest(id);
    try {
      const p = await testConnection(id);
      setProbes((prev) => ({ ...prev, [id]: p }));
    } catch (e) {
      setProbes((prev) => ({
        ...prev,
        [id]: { ok: false, elapsed_ms: 0, detail: e instanceof Error ? e.message : String(e) },
      }));
    } finally {
      setBusyTest(null);
    }
  };

  const columns: Column<Connection>[] = [
    {
      key: "id",
      header: "ID",
      width: "1.5fr",
      render: (r) => <span className="font-mono text-[12px]">{r.id}</span>,
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
            <Pill variant={p.ok ? "ok" : "failed"}>
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
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onTest(r.id); }}
            disabled={busyTest === r.id}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h disabled:opacity-50"
          >
            {busyTest === r.id ? "…" : "Test"}
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onDelete(r.id); }}
            disabled={busyDelete === r.id}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-red disabled:opacity-50"
          >
            {busyDelete === r.id ? "…" : "Delete"}
          </button>
        </span>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      onRowClick={(r) => router.push(`/connections/${encodeURIComponent(r.id)}/edit`)}
      emptyText="No connections yet. Create one to store credentials."
    />
  );
}
