"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { DataTable, type Column } from "@/components/ui";
import { triggerPipeline, type Pipeline } from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";

export function PipelinesTable({ rows }: { rows: Pipeline[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const { can } = usePermissions();
  const canTrigger = can("pipeline:trigger");

  const runPipeline = async (id: string) => {
    if (!id) {
      alert("This pipeline is missing an id and can't be triggered. Edit or delete it.");
      return;
    }
    setBusy(id);
    try {
      const { run_id } = await triggerPipeline(id);
      router.push(`/runs/${encodeURIComponent(run_id)}`);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  };

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
      key: "id",
      header: "ID",
      width: "180px",
      render: (r) => (
        <span className="font-mono text-[11px] text-subtle truncate">
          {r.id}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "80px",
      align: "right",
      render: (r) => canTrigger ? (
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
      ) : null,
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
