"use client";

import Link from "next/link";
import { DataTable, Pill, type Column } from "@/components/ui";
import type { Run } from "@/lib/api";

const pillFor = (s: Run["status"]) =>
  s === "completed" ? "ok" : s === "running" ? "running" : s === "failed" ? "failed" : "pending";

export function RunsTable({ runs }: { runs: Run[] }) {
  const columns: Column<Run>[] = [
    {
      key: "id",
      header: "Run",
      width: "180px",
      render: (r) => (
        <Link
          href={`/runs/${encodeURIComponent(r.id)}`}
          className="font-mono text-[12px] text-text hover:text-accent"
        >
          {r.id.slice(0, 8)}
        </Link>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "120px",
      render: (r) => <Pill status={pillFor(r.status)} />,
    },
    {
      key: "rows",
      header: "Rows",
      width: "110px",
      render: (r) => (
        <span className="font-mono text-[12px] text-text tabular-nums">
          {r.rows_written ?? "—"}
        </span>
      ),
    },
    {
      key: "started",
      header: "Started",
      width: "220px",
      render: (r) => (
        <span className="font-mono text-[11.5px] text-subtle">
          {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
        </span>
      ),
    },
    {
      key: "err",
      header: "Error",
      width: "1fr",
      render: (r) => (
        <span className="font-mono text-[11.5px] text-red truncate">
          {r.error ?? ""}
        </span>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={runs}
      emptyText="No runs yet — trigger one to get started."
    />
  );
}
