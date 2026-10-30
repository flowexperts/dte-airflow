import { Link } from "@/lib/nav";
import { CopyId, DataTable, Pill, type Column } from "@/components/ui";
import type { Run } from "@/lib/api";

const pillFor = (s: Run["status"]): "ok" | "running" | "failed" | "pending" =>
  s === "completed" || s === "completed_with_warnings"
    ? "ok"
    : s === "running"
      ? "running"
      : s === "failed" || s === "failed_quality"
        ? "failed"
        : "pending";

function QualityPill({ quality }: { quality: Run["quality"] }) {
  if (!quality) return <span className="font-mono text-[12px] text-subtle">—</span>;
  const total = quality.passed + quality.failed + quality.warned;
  if (total === 0) return <span className="font-mono text-[12px] text-subtle">—</span>;
  const passRate = Math.round((quality.passed / total) * 100);
  if (quality.failed > 0) {
    return <Pill status="failed">{passRate}%</Pill>;
  }
  if (quality.warned > 0) {
    return <Pill status="warn">{passRate}%</Pill>;
  }
  return <Pill status="ok">100%</Pill>;
}

export function RunsTable({ runs }: { runs: Run[] }) {
  const columns: Column<Run>[] = [
    {
      key: "id",
      header: "Run",
      width: "220px",
      render: (r) => (
        <span className="flex items-center gap-2 min-w-0">
          <Link
            href={`/runs/detail?id=${encodeURIComponent(r.id)}`}
            className="font-mono text-[12px] text-text hover:text-accent shrink-0"
          >
            {r.id.slice(0, 8)}
          </Link>
          <CopyId id={r.id} shorten />
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "120px",
      render: (r) => <Pill status={pillFor(r.status)} />,
    },
    {
      /* Why it ran. Beside Status because an unexpected failure asks "did
         something trigger this, or did someone?" before it asks anything
         else. */
      key: "trigger",
      header: "Trigger",
      width: "100px",
      render: (r) => (
        <span className="font-mono text-[11px] text-subtle">
          {r.scheduled ? "Scheduled" : "Manual"}
        </span>
      ),
    },
    {
      /* Which spec produced this. Sits next to Status because the two are
         read as a pair when a run fails: "it broke — on which version?"
         Links to the read-only revision so the answer is one click, not a
         diff hunt through History. */
      key: "revision",
      header: "Version",
      width: "110px",
      render: (r) =>
        r.revision_id ? (
          <Link
            href={`/pipelines/revision?id=${encodeURIComponent(r.pipeline_id)}&rev=${encodeURIComponent(r.revision_id)}`}
            className="font-mono text-[12px] text-muted hover:text-accent"
            title={`Pipeline as it stood for this run (${r.revision_id})`}
          >
            {r.revision_id.slice(0, 8)}
          </Link>
        ) : (
          <span className="font-mono text-[12px] text-subtle">—</span>
        ),
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
      key: "quality",
      header: "Quality",
      width: "100px",
      render: (r) => <QualityPill quality={r.quality} />,
    },
    {
      key: "err",
      header: "Error",
      width: "1fr",
      render: (r) => (
        <span className="font-mono text-[11.5px] text-red truncate">{r.error ?? ""}</span>
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
