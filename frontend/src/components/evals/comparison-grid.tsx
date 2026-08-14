"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Button, Panel, PanelHead, Pill } from "@/components/ui";
import { ScoreBar, pct, scoreTone } from "./score";
import {
  bootstrapEvalSet,
  getSweepComparison,
  type ComparisonCell,
  type SweepComparison,
} from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { usePermissions } from "@/lib/use-permissions";
import { cn } from "@/lib/cn";

/**
 * Several extraction configs, side by side, over the same documents.
 *
 * The page deliberately renders in full with **no labels at all**. Plan
 * 051's leaderboard opened on "No comparable runs yet", which meant the
 * only thing the harness showed a new user was a demand for work they had
 * not done — and hand-labelling a corpus is nobody's Tuesday, so the
 * harness stayed empty.
 *
 * Everything above the score column needs no ground truth: which configs
 * disagree and where, what each cost, how slow each was, how often each
 * abstained. That is most of the decision. Scores appear in the same cards
 * once labels exist.
 *
 * And the ordering closes the loop: disagreements sort first, because they
 * are simultaneously the reason to read the page and the queue you would
 * label from. "Accept N agreed" turns the rest into ground truth in one
 * click, at which point the same page starts ranking.
 */

const cellLabel = (cell: ComparisonCell): string => {
  const c = cell.cell ?? {};
  const parts = [c.provider, c.model].filter(Boolean) as string[];
  return parts.length > 0 ? parts.join(" · ") : cell.pipeline_id;
};

const money = (v: number | null): string => (v == null ? "—" : `$${v.toFixed(4)}`);
const ms = (v: number | null): string => (v == null ? "—" : `${v}ms`);

function CellCard({ cell, scored }: { cell: ComparisonCell; scored: boolean }) {
  const running = cell.status === "pending" || cell.status === "running";
  return (
    <Panel className="min-w-[220px] flex-1">
      <div className="px-3.5 py-2.5 border-b border-border flex items-center justify-between gap-2">
        <span className="text-[13px] text-text truncate">{cellLabel(cell)}</span>
        {/* A leader that nothing else ties gets the badge. A leader inside
            someone else's confidence interval does not — declaring a winner
            on noise sends people off to ship a config that is not better. */}
        {scored && cell.rank === 1 && !cell.tied_with_leader && (
          <Pill status="ok">best</Pill>
        )}
        {scored && cell.tied_with_leader && <Pill status="pending">tied</Pill>}
        {running && <Pill status="running">running</Pill>}
        {cell.status === "failed" && <Pill status="failed">failed</Pill>}
        {/* A run can complete green with every call having failed —
            `on_error: null` fills nulls rather than failing the run. Without
            this the column is a wall of em dashes indistinguishable from a
            model that looked and found nothing. */}
        {cell.error_count > 0 && <Pill status="warn">{cell.error_count} errored</Pill>}
      </div>
      <div className="px-3.5 py-3 flex flex-col gap-2">
        {scored && (
          <div className="flex items-center gap-2">
            <ScoreBar value={cell.macro_f1 ?? null} interval={cell.macro_f1_interval ?? undefined} />
            <span className="font-mono text-[11px] text-subtle">n={cell.n ?? 0}</span>
          </div>
        )}
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11.5px] tabular-nums">
          <dt className="text-subtle">cost</dt>
          <dd>{money(cell.cost_usd)}</dd>
          <dt className="text-subtle">p95</dt>
          <dd>{ms(cell.latency_p95_ms)}</dd>
          <dt className="text-subtle">blank</dt>
          {/* Abstention is not the same as being wrong. A config that
              answers nothing must not read as clean. */}
          <dd style={{ color: cell.null_rate && cell.null_rate > 0.2 ? "var(--gold)" : undefined }}>
            {pct(cell.null_rate)}
          </dd>
          <dt className="text-subtle">docs</dt>
          <dd>{cell.documents}</dd>
        </dl>
        {cell.error && (
          <p className="text-[11.5px] text-red break-words">{cell.error}</p>
        )}
        {/* The provider's own words. "Could not resolve authentication
            method" is a fixable thing; a blank column is not. */}
        {cell.error_sample && (
          <p className="text-[11.5px] text-red break-words">{cell.error_sample}</p>
        )}
      </div>
    </Panel>
  );
}

export function ComparisonGrid({ sweepId }: { sweepId: string }) {
  const { can } = usePermissions();
  const toast = useToast();
  const [accepting, setAccepting] = useState(false);

  const { data, error, mutate } = useSWR<SweepComparison>(
    ["sweep-comparison", sweepId],
    () => getSweepComparison(sweepId),
    // Poll only while cells are outstanding. A finished comparison is
    // static, and re-materialising it on a timer costs a compile per tick.
    { refreshInterval: (latest) => ((latest?.pending ?? 0) > 0 ? 2500 : 0) },
  );

  if (error) {
    return (
      <Panel>
        <div className="px-4 py-4 text-[12.5px] text-red">
          {humanizeError(error, { action: "load", entity: "comparison" }).message}
        </div>
      </Panel>
    );
  }
  if (!data) {
    return <p className="text-[12.5px] text-muted">Loading comparison…</p>;
  }

  const scored = data.cells.some((c) => c.macro_f1 != null);
  const fieldNames = data.fields.map((f) => f.name);
  const disagreeing = data.documents.filter((d) => d.agrees === false).length;

  const acceptAgreed = async () => {
    setAccepting(true);
    try {
      const res = await bootstrapEvalSet(
        data.eval_set_id,
        data.cells.map((c) => c.pipeline_id),
        true,
      );
      toast.success({
        title: `Labelled ${res.written ?? data.labels.agreed_unlabeled} documents`,
        message: "Scores appear as each config is re-scored.",
      });
      void mutate();
    } catch (e) {
      toast.error(humanizeError(e, { action: "label", entity: "documents" }));
    } finally {
      setAccepting(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex gap-3 flex-wrap">
        {data.cells.map((c) => (
          <CellCard key={c.cell_id} cell={c} scored={scored} />
        ))}
      </div>

      {!scored && (
        <Panel>
          <div className="px-4 py-3 flex items-center justify-between gap-4 flex-wrap">
            <p className="text-[12.5px] text-muted max-w-[62ch]">
              {disagreeing > 0 ? (
                <>
                  These configs disagree on{" "}
                  <strong className="text-text">{disagreeing}</strong> of{" "}
                  {data.documents.length} documents. Those are the ones worth
                  reading — the rest they already settled between them.
                </>
              ) : (
                <>
                  Every config agreed on all {data.documents.length} documents.
                  That usually means the task is easy enough for the cheapest
                  option.
                </>
              )}
            </p>
            {can("eval:write") && data.labels.agreed_unlabeled > 0 && (
              <Button
                variant={data.labels.auto_accept ? "primary" : "default"}
                size="sm"
                disabled={accepting || !data.labels.auto_accept}
                onClick={() => void acceptAgreed()}
              >
                {accepting
                  ? "Labelling…"
                  : `Accept ${data.labels.agreed_unlabeled} agreed as labels`}
              </Button>
            )}
          </div>
          {/* The write is refused when every config shares a provider, and
              that is the common case — sweeping models or prompts holds the
              provider fixed. Saying so beside a disabled button beats a
              primary button that 409s on click. */}
          {data.labels.warning && data.labels.agreed_unlabeled > 0 && (
            <div className="px-4 pb-3 -mt-1">
              <p className="text-[11.5px] text-subtle max-w-[72ch]">
                {data.labels.warning} Add a second provider to the comparison,
                or label these from the{" "}
                <Link
                  href={`/eval-sets/${encodeURIComponent(data.eval_set_id)}?tab=review`}
                  className="text-text underline underline-offset-2"
                >
                  review queue
                </Link>
                .
              </p>
            </div>
          )}
        </Panel>
      )}

      {data.fields.some((f) => f.agreement_rate != null) && (
        <Panel>
          <PanelHead label="Agreement by field" />
          <div className="px-4 py-3 flex flex-col gap-2">
            {data.fields.map((f) => (
              <div key={f.name} className="flex items-center gap-3">
                <span className="font-mono text-[12px] w-[160px] truncate">{f.name}</span>
                <span className="relative inline-block h-[6px] w-[160px] rounded-full bg-hover overflow-hidden">
                  <span
                    className="absolute inset-y-0 left-0"
                    style={{
                      width: `${(f.agreement_rate ?? 0) * 100}%`,
                      background: scoreTone(f.agreement_rate),
                    }}
                  />
                </span>
                <span className="font-mono text-[12px] tabular-nums">
                  {pct(f.agreement_rate)}
                </span>
                <span className="text-[11.5px] text-subtle">
                  {f.disagreement_count === 0
                    ? "all agree"
                    : `${f.disagreement_count} differ`}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel>
        <PanelHead label="Documents" count={data.documents.length} />
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left font-normal text-subtle px-4 py-2">Document</th>
                <th className="text-left font-normal text-subtle px-3 py-2">Field</th>
                {data.cells.map((c) => (
                  <th key={c.cell_id} className="text-left font-normal text-subtle px-3 py-2">
                    {cellLabel(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.documents.map((doc) =>
                fieldNames.map((field, i) => {
                  const values = data.cells.map((c) => doc.values[c.cell_id]?.[field]);
                  const differs =
                    new Set(values.map((v) => JSON.stringify(v ?? null))).size > 1;
                  return (
                    <tr
                      key={`${doc.doc_key}:${field}`}
                      className={cn("border-b border-border/50", differs && "bg-gold/5")}
                    >
                      {i === 0 && (
                        <td
                          rowSpan={fieldNames.length}
                          className="px-4 py-2 align-top border-r border-border/50"
                        >
                          <Link
                            href={`/documents/${doc.doc_key}`}
                            className="font-mono text-[11.5px] text-muted hover:text-text break-all"
                          >
                            {doc.doc_ref ?? `${doc.doc_key.slice(0, 12)}…`}
                          </Link>
                        </td>
                      )}
                      <td className="px-3 py-2 font-mono text-[11.5px] text-subtle">
                        {field}
                      </td>
                      {values.map((v, vi) => (
                        <td
                          key={data.cells[vi]!.cell_id}
                          className={cn(
                            "px-3 py-2 font-mono text-[11.5px]",
                            // Null is not a wrong answer, it is no answer.
                            // Rendering it as an em dash rather than empty
                            // keeps the column readable at a glance.
                            v == null && "text-subtle",
                          )}
                        >
                          {v == null ? "—" : String(v)}
                        </td>
                      ))}
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
