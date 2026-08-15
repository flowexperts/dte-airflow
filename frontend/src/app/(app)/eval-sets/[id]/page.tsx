"use client";

import { use, useState } from "react";
import useSWR from "swr";
import {
  InlineError,
  Metric,
  MetricRow,
  PageHeader,
  Tabs,
  Topbar,
  type TabOption,
} from "@/components/ui";
import { getEvalSet, type EvalSet } from "@/lib/api";
import { ExamplesPanel } from "@/components/evals/examples-panel";
import { LeaderboardPanel } from "@/components/evals/leaderboard";
import { ReviewPanel } from "@/components/evals/review-panel";
import { RunEvalButton } from "@/components/evals/run-eval-button";
import { SweepLauncher } from "@/components/evals/sweep-launcher";

type Tab = "leaderboard" | "examples" | "review";

const TABS: TabOption<Tab>[] = [
  { value: "leaderboard", label: "Leaderboard" },
  { value: "examples", label: "Examples" },
  { value: "review", label: "Review" },
];

export default function EvalSetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [tab, setTab] = useState<Tab>("leaderboard");

  const { data: set, error } = useSWR<EvalSet>(["eval-set", id], () => getEvalSet(id));

  const onTab = (v: Tab) => {
    setTab(v);
    // Query-string addressable, matching the pipeline canvas: the default tab
    // drops the param so the bare URL stays canonical.
    const url = new URL(window.location.href);
    if (v === "leaderboard") url.searchParams.delete("tab");
    else url.searchParams.set("tab", v);
    window.history.replaceState(null, "", url.toString());
  };

  if (error) {
    return (
      <div className="px-14 py-8">
        <InlineError title="Couldn't load this eval set" message="It may have been deleted." />
      </div>
    );
  }

  const labeled = set?.example_count ?? 0;
  const holdout = set?.holdout_count ?? 0;

  return (
    <>
      <Topbar
        crumbs={[
          { label: "Workspace", href: "/" },
          { label: "Eval sets", href: "/eval-sets" },
          { label: set?.name ?? id },
        ]}
      />
      <PageHeader
        title={set?.name ?? id}
        sub={set ? `${set.field_specs.length} fields · labels v${set.labels_version}` : ""}
        lede={
          set
            ? `Scoring ${set.field_specs.map((f) => f.name).join(", ")} against ${labeled} labeled documents.`
            : ""
        }
      />

      <div className="px-14 pb-4">
        <MetricRow>
          <Metric label="Labeled" value={String(labeled)} />
          {/* Holdout is excluded from the headline score and reported
              separately — a large train/holdout gap means the config was
              tuned to the eval set. */}
          <Metric label="Holdout" value={holdout ? String(holdout) : "—"} />
          <Metric label="Fields" value={String(set?.field_specs.length ?? 0)} />
          <Metric label="Labels version" value={set ? `v${set.labels_version}` : "—"} />
        </MetricRow>
      </div>

      {set?.judge_labeled_warning && (
        <div className="px-14 pb-2">
          <div
            className="text-[12.5px] px-3 py-2 rounded-[var(--radius)] border"
            style={{ borderColor: "var(--gold)", color: "var(--gold)" }}
          >
            {set.judge_labeled_warning}
          </div>
        </div>
      )}

      <div className="sticky top-[52px] z-10 bg-bg px-14">
        <div className="flex items-center gap-4">
          <Tabs value={tab} onChange={onTab} options={TABS} />
          <span className="relative ml-auto shrink-0">
            <RunEvalButton evalSetId={id} />
          </span>
        </div>
      </div>

      <div className="px-14 py-8">
        {tab === "leaderboard" && (
          <div className="flex flex-col gap-6">
            <SweepLauncher evalSetId={id} />
            <LeaderboardPanel evalSetId={id} />
          </div>
        )}
        {tab === "examples" && set && <ExamplesPanel evalSet={set} />}
        {tab === "review" && set && <ReviewPanel evalSet={set} />}
      </div>
    </>
  );
}
