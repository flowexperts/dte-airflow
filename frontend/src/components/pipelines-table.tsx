"use client";

import { useRouter } from "next/navigation";
import { DataTable, type Column } from "@/components/ui";
import type { Pipeline } from "@/lib/api";

export function PipelinesTable({ rows }: { rows: Pipeline[] }) {
  const router = useRouter();

  const columns: Column<Pipeline>[] = [
    {
      key: "idx",
      header: "#",
      width: "32px",
      render: (_, i) => (
        <span className="font-mono text-[10.5px] text-subtle">
          {String(i + 1).padStart(2, "0")}
        </span>
      ),
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
            {r.output?.path}
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
      key: "id",
      header: "ID",
      width: "220px",
      render: (r) => (
        <span className="font-mono text-[11px] text-subtle truncate">
          {r.id}
        </span>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      onRowClick={(r) => router.push(`/pipelines/${encodeURIComponent(r.id)}`)}
      emptyText="No pipelines yet. Create your first one."
    />
  );
}
