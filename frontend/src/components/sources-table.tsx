"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { DataTable, type Column } from "@/components/ui";
import { deleteSource, type Source } from "@/lib/api";

export function SourcesTable({ rows }: { rows: Source[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);

  const onDelete = async (id: string) => {
    if (!confirm(`Delete source '${id}'?`)) return;
    setBusy(id);
    try {
      await deleteSource(id);
      router.refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const columns: Column<Source>[] = [
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
      render: (r) => (
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
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      onRowClick={(r) => router.push(`/sources/${encodeURIComponent(r.id)}/edit`)}
      emptyText="No sources yet. Create one to reuse across pipelines."
    />
  );
}
