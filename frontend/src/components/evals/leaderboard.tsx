"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Panel, PanelHead, Pill, InlineError } from "@/components/ui";
import {
  getFieldFailures,
  type FieldFailure,
  type Leaderboard,
  type LeaderboardEntry,
} from "@/lib/api";
import { PromoteButton } from "./promote-button";
import { rootPipelineId } from "@/lib/pipeline-variant";
import {
  FieldChip,
  SampleSize,
  ScoreBar,
  StaleBadge,
  ThroughputChips,
  TiedBadge,
  pct,
} from "./score";

/**
 * The leaderboard.
 *
 * Rank comes from the server, which refuses to separate configs whose
 * confidence intervals overlap. This component must not invent an ordering
 * the backend declined to assert, so it renders `ranking` as given and shows
 * stale runs in a separate, unranked section.
 */
export function LeaderboardPanel({ evalSetId }: { evalSetId: string }) {
  const { data, error } = useSWR<Leaderboard>(
    `/api/eval-sets/${encodeURIComponent(evalSetId)}/leaderboard`,
  );
  const [openField, setOpenField] = useState<{ runId: string; field: string } | null>(null);

  if (error) {
    return (
      <InlineError
        title="Couldn't load the leaderboard"
        message="The eval runs for this set didn't come back."
      />
    );
  }
  if (!data) return <div className="text-muted text-[13px] px-1 py-6">Loading…</div>;

  const ranked = data.ranking;
  const stale = data.entries.filter((e) => e.stale);

  return (
    <div className="flex flex-col gap-6">
      {data.judge_labeled_warning && (
        <div
          className="text-[12.5px] px-3 py-2 rounded-[var(--radius)] border"
          style={{ borderColor: "var(--gold)", color: "var(--gold)" }}
        >
          {data.judge_labeled_warning}
        </div>
      )}

      <Panel>
        <PanelHead
          label="Leaderboard"
          count={`labels v${data.labels_version}`}
        />
        {ranked.length === 0 ? (
          <div className="px-4 py-8 text-[13px] text-muted">
            No comparable runs yet. Trigger an eval pipeline against this set to
            get a score.
          </div>
        ) : (
          ranked.map((entry) => (
            <RunRow
              key={entry.run_id}
              evalSetId={evalSetId}
              entry={entry}
              onFieldClick={(field) => setOpenField({ runId: entry.run_id, field })}
            />
          ))
        )}
      </Panel>

      {stale.length > 0 && (
        <Panel>
          <PanelHead
            label="Scored against older labels"
            count={stale.length}
          />
          <div className="px-4 py-2.5 text-[12.5px] text-muted border-b border-border">
            These ran before the labels changed. They are kept for history and
            excluded from ranking — comparing across a label edit measures the
            labels, not the extractor.
          </div>
          {stale.map((entry) => (
            <RunRow key={entry.run_id} entry={entry} onFieldClick={() => {}} />
          ))}
        </Panel>
      )}

      {openField && (
        <FailuresPanel
          evalSetId={evalSetId}
          runId={openField.runId}
          field={openField.field}
          onClose={() => setOpenField(null)}
        />
      )}
    </div>
  );
}

function RunRow({
  entry,
  onFieldClick,
  evalSetId,
}: {
  entry: LeaderboardEntry;
  onFieldClick: (field: string) => void;
  evalSetId?: string | undefined;
}) {
  return (
    <div className="border-b border-border last:border-b-0 px-4 py-3 flex flex-col gap-2">
      <div className="flex items-center gap-3 flex-wrap">
        {entry.rank != null && (
          <span className="font-mono text-[12px] text-subtle tabular-nums w-5">
            {entry.rank}
          </span>
        )}
        <ScoreBar value={entry.macro_f1} interval={entry.macro_f1_interval} />
        <SampleSize n={entry.n} />
        {entry.tied_with_leader && <TiedBadge />}
        {entry.stale && <StaleBadge />}
        {entry.regression && (
          <span
            className="text-[11px] px-1.5 py-0.5 rounded-[var(--radius)]"
            style={{ background: "var(--red-tint, transparent)", color: "var(--red)" }}
            title={`Down ${(entry.regression.drop * 100).toFixed(1)}pp from ${entry.regression.previous_run_id.slice(0, 8)} at the same config`}
          >
            regressed
          </span>
        )}
        <span className="ml-auto flex items-center gap-2.5">
          {entry.holdout && (
            <span
              className="text-[11.5px] text-muted"
              title="Holdout examples are excluded from the headline score. A large gap means the config was tuned to the eval set."
            >
              holdout {pct(entry.holdout.macro_f1)}
            </span>
          )}
          <Pill status={entry.status === "completed" ? "ok" : entry.status === "failed" ? "failed" : "warn"}>
            {entry.status}
          </Pill>
        </span>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <span
          className="font-mono text-[11px] text-subtle"
          title="Identity of the extract + structure config. Same digest and a different score later means the provider moved, not your pipeline."
        >
          {entry.config_digest?.slice(0, 12) ?? "—"}
        </span>
        <span className="text-[11.5px] text-subtle">{entry.pipeline_id}</span>
        {/* A leaderboard row from a sweep is one cell of a comparison, and
            the comparison shows what the ranking cannot: where the configs
            actually disagreed, on which documents. The link existed in the
            data all along and was never rendered. */}
        {entry.sweep_id && (
          <Link
            href={`/pipelines/${encodeURIComponent(rootPipelineId(entry.pipeline_id))}/compare?sweep=${encodeURIComponent(entry.sweep_id)}`}
            className="text-[11.5px] text-muted hover:text-text underline underline-offset-2"
            title="Open the side-by-side comparison this run belongs to"
          >
            in comparison
          </Link>
        )}
        <ThroughputChips t={entry.throughput} />
        {entry.fields.map((f) => (
          <button
            key={f.name}
            type="button"
            onClick={() => onFieldClick(f.name)}
            className="cursor-pointer bg-transparent border-0 p-0"
            title={`Show the documents where ${f.name} did not match`}
          >
            <FieldChip metrics={f} />
          </button>
        ))}
        {/* Only offered on runs still scored against the current labels —
            promoting a config whose score is stale ships a number that no
            longer means what it says. */}
        {evalSetId && !entry.stale && (
          <span className="ml-auto">
            <PromoteButton evalSetId={evalSetId} pipelineId={entry.pipeline_id} />
          </span>
        )}
      </div>
    </div>
  );
}

function FailuresPanel({
  evalSetId,
  runId,
  field,
  onClose,
}: {
  evalSetId: string;
  runId: string;
  field: string;
  onClose: () => void;
}) {
  const { data, error } = useSWR(
    [`failures`, evalSetId, field, runId],
    () => getFieldFailures(evalSetId, field, runId),
  );

  return (
    <Panel>
      <PanelHead
        label={`${field} — failures`}
        count={
          <button
            type="button"
            onClick={onClose}
            className="text-[12px] text-subtle hover:text-text bg-transparent border-0 cursor-pointer"
          >
            Close
          </button>
        }
      />
      {error && (
        <div className="px-4 py-4 text-[13px] text-muted">
          Couldn&apos;t load failures for this field.
        </div>
      )}
      {data && data.failures.length === 0 && (
        <div className="px-4 py-6 text-[13px] text-muted">
          No failures — every labeled document matched on {field}.
        </div>
      )}
      {data?.failures.map((f: FieldFailure) => (
        <div
          key={`${f.doc_key}-${f.field}`}
          className="border-b border-border last:border-b-0 px-4 py-2.5"
        >
          <div className="font-mono text-[11px] text-subtle mb-1">
            {f.doc_ref ?? f.doc_key.slice(0, 16)}
            {f.split === "holdout" && (
              <span className="ml-2 text-[10.5px]">holdout</span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3 text-[12.5px]">
            <div>
              <span className="text-subtle text-[11px] block">expected</span>
              <span style={{ color: "var(--green)" }} className="font-mono">
                {String(f.expected ?? "—")}
              </span>
            </div>
            <div>
              <span className="text-subtle text-[11px] block">got</span>
              <span style={{ color: "var(--red)" }} className="font-mono line-through">
                {String(f.actual ?? "—")}
              </span>
            </div>
          </div>
        </div>
      ))}
    </Panel>
  );
}
