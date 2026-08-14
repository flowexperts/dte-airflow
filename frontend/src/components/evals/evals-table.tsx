"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CopyId, DataTable, type Column } from "@/components/ui";
import { deleteEvalSet, type EvalSet } from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { ScoreBar } from "./score";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";

/** Share of labels that came from a model rather than a person. */
function judgeShare(set: EvalSet): number {
  const sources = set.label_sources ?? {};
  const total = Object.values(sources).reduce((a, b) => a + b, 0);
  return total ? (sources.judge ?? 0) / total : 0;
}

export function EvalSetsTable({ rows }: { rows: EvalSet[] }) {
  const router = useRouter();
  const { can } = usePermissions();
  const canDelete = can("eval:delete");
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();

  const onDelete = async (id: string) => {
    if (!confirm(`Delete eval set '${id}'? Its labels go with it.`)) return;
    setBusy(id);
    try {
      await deleteEvalSet(id);
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "eval set" }));
    } finally {
      setBusy(null);
    }
  };

  const columns: Column<EvalSet>[] = [
    {
      key: "name",
      header: "Name",
      render: (r) => (
        <div className="flex flex-col gap-0.5">
          <span className="text-text">{r.name}</span>
          <CopyId id={r.id} />
        </div>
      ),
    },
    {
      key: "field_specs",
      header: "Fields",
      render: (r) => (
        <span className="font-mono text-[12px] text-muted">
          {r.field_specs.map((f) => f.name).join(", ")}
        </span>
      ),
    },
    {
      key: "example_count",
      header: "Labeled",
      render: (r) => (
        <span className="font-mono text-[12px] tabular-nums">
          {r.example_count ?? 0}
        </span>
      ),
    },
    {
      key: "label_sources",
      header: "Label source",
      render: (r) => {
        const share = judgeShare(r);
        if (!r.example_count) return <span className="text-subtle">—</span>;
        return (
          <span
            className="text-[12px]"
            style={{ color: share > 0.5 ? "var(--gold)" : "var(--muted)" }}
            title={
              share > 0.5
                ? "Majority of these labels came from an LLM judge — scores partly measure agreement with a model."
                : undefined
            }
          >
            {Object.entries(r.label_sources ?? {})
              .map(([k, v]) => `${k} ${v}`)
              .join(" · ")}
          </span>
        );
      },
    },
    {
      key: "best_macro_f1",
      header: "Best F1",
      render: (r) => (
        // Against current labels only. A score earned before the labels were
        // corrected is not this set's best, and putting it here would
        // contradict the leaderboard, which greys that run out.
        <ScoreBar value={r.best_macro_f1 ?? null} width={80} />
      ),
    },
    {
      key: "last_run_at",
      header: "Last run",
      render: (r) => (
        <span className="font-mono text-[11.5px] text-subtle tabular-nums">
          {/* ISO slice, not toLocaleDateString: `/eval-sets` is a server
              component, so the first paint is rendered with the *server's*
              locale and then re-rendered with the browser's — 14/8/2026 vs
              8/14/2026 is a hydration mismatch that discards the tree. */}
          {r.last_run_at ? r.last_run_at.slice(0, 10) : "never"}
        </span>
      ),
    },
    {
      key: "labels_version",
      header: "Labels v",
      render: (r) => (
        <span className="font-mono text-[12px] text-subtle tabular-nums">
          v{r.labels_version}
        </span>
      ),
    },
    ...(canDelete
      ? [
          {
            key: "actions",
            header: "",
            render: (r: EvalSet) => (
              <button
                type="button"
                className="text-[12px] text-subtle hover:text-[color:var(--red)] disabled:opacity-50"
                disabled={busy === r.id}
                onClick={(e) => {
                  e.stopPropagation();
                  void onDelete(r.id);
                }}
              >
                {busy === r.id ? "Deleting…" : "Delete"}
              </button>
            ),
          } as Column<EvalSet>,
        ]
      : []),
  ];

  return (
    <DataTable
      rows={rows}
      columns={columns}
      onRowClick={(r) => router.push(`/eval-sets/${encodeURIComponent(r.id)}`)}
      emptyText="No eval sets yet. An eval set is a labeled corpus — it turns 'this prompt looks right' into a number you can compare."
    />
  );
}
