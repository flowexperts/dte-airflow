import { useState } from "react";
import { Link } from "@/lib/nav";
import { useRouter, useSearchParams } from "@/lib/nav";
import {
  Button,
  Field,
  Input,
  Item,
  PageHeader,
  Panel,
  PanelHead,
  Tabs,
  Tag,
  Topbar,
} from "@/components/ui";
import { SchemaProvider } from "@/components/builder/schema-context";
import { PipelineParamsProvider } from "@/components/builder/params-context";
import { SourcesPanel } from "@/components/builder/sources";
import { DestinationPicker } from "@/components/builder/DestinationPicker";
import { InputsPanel } from "@/components/builder/InputsPanel";
import { SchedulePanel } from "@/components/builder/schedules/SchedulePanel";
import { NotificationsPanel } from "@/components/builder/notifications/NotificationsPanel";
import type { StepShape } from "@/components/builder/steps/types";
import {
  updatePipeline,
  type Destination,
  type Pipeline,
  type PipelineRevision,
  type Source,
  type SourceTableRef,
} from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { usePermissions } from "@/lib/use-permissions";
import { cn } from "@/lib/cn";
import { AutoInferSchemas, AutoStepSchemas } from "./schema-sync";
import { TriggerRunButton } from "./trigger";
import { CompareButton } from "./compare-button";
import {
  RunTone,
  destinationPathLabel,
  pipelineShape,
  runOutcome,
  sourcePathLabel,
} from "./helpers";
import { StepsColumn } from "./steps-column";
import { Rail } from "./rail";
import { RevisionYaml } from "@/components/builder/history/YamlDiff";
import { HistoryPane, RunsPane, usePipelineRuns } from "./activity";
import { ComparisonsPane, usePipelineComparisons } from "@/components/evals/comparisons-panel";

type PipelineView = "spec" | "runs" | "history" | "comparisons";

/** Read-only sources, for viewers without write permission. */
function SourcesCard({ sources, refs }: { sources: (Source | null)[]; refs: SourceTableRef[] }) {
  return (
    <Panel>
      <PanelHead label="Sources" count={refs.length} />
      {refs.length === 0 && <div className="px-4 py-4 text-sm text-subtle">No sources.</div>}
      {sources.map((s, i) => {
        const ref = refs[i];
        return s ? (
          <Item
            key={`${s.id}-${i}`}
            glyph="§"
            label={ref?.alias ?? s.id}
            path={ref?.table ? `${ref.table} — ${sourcePathLabel(s)}` : sourcePathLabel(s)}
            tag={<Tag>{s.source_type}</Tag>}
          />
        ) : (
          <Item
            key={`${ref?.source_id ?? i}-${i}`}
            glyph="§"
            label={ref?.alias || ref?.source_id || "?"}
            path="(source not found)"
            tag={<Tag>missing</Tag>}
          />
        );
      })}
    </Panel>
  );
}

/**
 * What a quality pipeline has instead of an output. The current detail page
 * renders "Output → (destination not found)" here, which is worse than saying
 * nothing — a quality pipeline is not missing a destination, it doesn't have one.
 */
function QualityReportCard({ pipeline }: { pipeline: Pipeline }) {
  const checks = (pipeline.steps ?? []).filter(
    (s) => s.op === "check" || s.op === "profile",
  ).length;
  return (
    <Panel>
      <PanelHead label="Output" count={<span className="text-subtle">report</span>} />
      <div className="px-4 py-3.5">
        <p className="text-[13px] text-muted m-0">
          Quality pipelines write no data. Each run evaluates{" "}
          <b className="text-text font-medium">
            {checks} check{checks === 1 ? "" : "s"}
          </b>{" "}
          and reports pass/fail.
        </p>
      </div>
    </Panel>
  );
}

function DestinationCard({
  pipeline,
  destination,
}: {
  pipeline: Pipeline;
  destination: Destination | null;
}) {
  return (
    <Panel>
      <PanelHead label="Destination" count={1} />
      {destination ? (
        <Item
          glyph="¶"
          label={destination.id}
          path={destinationPathLabel(destination)}
          tag={<Tag variant="output">{destination.config.type}</Tag>}
        />
      ) : (
        <Item
          glyph="¶"
          label={pipeline.output_id || "—"}
          path="(destination not found)"
          tag={<Tag variant="output">missing</Tag>}
        />
      )}
    </Panel>
  );
}

export function PipelineCanvas({
  initialPipeline,
  sources,
  destination,
  revision,
}: {
  initialPipeline: Pipeline;
  sources: (Source | null)[];
  destination: Destination | null;
  /** Set when viewing a historical revision: the canvas becomes read-only,
   *  the tabs and run controls go away, and a banner names what you're
   *  looking at. Past configs are evidence, not drafts — letting them be
   *  edited would silently fork the pipeline from a run's record of it. */
  revision?: PipelineRevision;
}) {
  const router = useRouter();
  const toast = useToast();
  const { can } = usePermissions();
  const canEdit = can("pipeline:write") && !revision;

  const [pipeline, setPipeline] = useState<Pipeline>(initialPipeline);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [openStep, setOpenStep] = useState<number | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  /* The tab lives in the URL (`?tab=runs`), not just in state, so it can be
   * linked to — a run's breadcrumb points back at the pipeline's Runs tab,
   * and Back returns to the tab you were on. Written with the History API
   * rather than router.replace: this is a client-side view switch, and a
   * router navigation would re-run the server component for no gain. */
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const [view, setView] = useState<PipelineView>(
    tabParam === "runs" || tabParam === "history" || tabParam === "comparisons" ? tabParam : "spec",
  );

  const changeView = (next: PipelineView) => {
    setView(next);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (next === "spec") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.replaceState(window.history.state, "", url);
  };

  /* Same gate as the Compare… button: without a `structure` step there is
     nothing to compare configs *of*. Derived from the spec rather than from
     the comparisons list, so the tab strip does not reflow once an async
     fetch lands. */
  const comparable = (pipeline.steps ?? []).some((s) => (s as { op?: string }).op === "structure");
  const { data: comparisonsData } = usePipelineComparisons(pipeline.id);
  const comparisonCount = comparisonsData?.comparisons?.length ?? 0;

  /* Fetched at the canvas level, not inside the Runs pane: the tab badge
     shows last-run health on every tab, so the spec view answers "is this
     healthy?" without a click. */
  const runs = usePipelineRuns(initialPipeline.id);
  const lastRun = runs[0];

  const steps = (pipeline.steps ?? []) as StepShape[];
  const quality = pipeline.pipeline_type === "quality";

  /** Every mutation goes through here so `dirty` can't drift from the state. */
  const patch = (next: Partial<Pipeline>) => {
    setPipeline((p) => ({ ...p, ...next }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await updatePipeline(pipeline.id, pipeline);
      setDirty(false);
      toast.success({ title: "Pipeline saved" });
      router.refresh();
    } catch (e) {
      toast.error(humanizeError(e, { action: "save", entity: "pipeline" }));
    } finally {
      setSaving(false);
    }
  };

  const sourcesBlock = canEdit ? (
    <SourcesPanel sources={pipeline.sources ?? []} onChange={(next) => patch({ sources: next })} />
  ) : (
    <SourcesCard sources={sources} refs={pipeline.sources ?? []} />
  );

  const outputBlock = quality ? (
    <QualityReportCard pipeline={pipeline} />
  ) : canEdit ? (
    <DestinationPicker
      outputId={pipeline.output_id ?? ""}
      onChange={(output_id) => patch({ output_id })}
    />
  ) : (
    <DestinationCard pipeline={pipeline} destination={destination} />
  );

  const stepsBlock = (
    <StepsColumn
      steps={steps}
      onChange={(next) => patch({ steps: next as Pipeline["steps"] })}
      pipelineType={pipeline.pipeline_type ?? "transform"}
      openIndex={openStep}
      onOpenChange={setOpenStep}
      readOnly={!canEdit}
      sources={pipeline.sources ?? []}
      outputId={pipeline.output_id ?? ""}
    />
  );

  /* The name, first — it is what the page is about and the first thing
   * anyone renames. Behind a disclosure it was three clicks from the top of
   * a page already titled with it. Identity (id, type) rides along because
   * it answers "am I on the right pipeline?", asked in the same glance. */
  const identityBlock = (
    <Panel>
      <PanelHead label="Pipeline" />
      <div className="px-3.5 py-3.5 space-y-3">
        {canEdit ? (
          <Field label="Name" hint="editable; unique per workspace">
            <Input value={pipeline.name} onChange={(e) => patch({ name: e.target.value })} />
          </Field>
        ) : (
          <Field label="Name">
            <span className="text-[13px] text-muted">{pipeline.name}</span>
          </Field>
        )}
        <div className="font-mono text-[11px] text-subtle">
          {pipeline.id} · {quality ? "quality" : "transform"}
        </div>
      </div>
    </Panel>
  );

  /* Inputs sit immediately above the schedule, because a schedule supplies
   * values for them: the schedule form collects one value per declared
   * input, and a required input with no value fails every scheduled run.
   * Declaring has to come before scheduling, so it reads in that order. */
  /* No wrapping Panel — InputsPanel brings its own Panel and header. */
  const inputsBlock = canEdit ? (
    <InputsPanel params={pipeline.params ?? []} onChange={(params) => patch({ params })} />
  ) : null;

  /* What's left after name and inputs moved out. Kept collapsed — nothing
   * here is touched during ordinary editing. */
  const settingsBlock = (
    <Panel>
      <button
        type="button"
        onClick={() => setSettingsOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 hover:bg-hover transition-colors text-left"
      >
        <span className="flex items-center gap-2">
          <span
            className={cn(
              "text-[9px] text-muted inline-block transition-transform",
              settingsOpen && "rotate-90",
            )}
          >
            ▶
          </span>
          <span className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
            Advanced
          </span>
        </span>
      </button>
      {settingsOpen && (
        <div className="border-t border-border px-3.5 py-3.5 space-y-4">
          <div className="font-mono text-[11px] text-subtle">
            engine: {pipeline.engine ?? "duckdb"}
          </div>
        </div>
      )}
    </Panel>
  );

  /* When it runs, sitting with where it reads from and writes to.
   *
   * A schedule is part of the pipeline's contract — in, out, and when — not
   * an operational afterthought, so it belongs in the spec column beside the
   * endpoints rather than on a settings page you have to go find. Placed
   * after the destination so the column reads in → out → when, with the
   * steps (the body) following.
   *
   * Hidden on a revision: the panel edits the *current* schedule, and a
   * historical spec's schedule lives in that revision's own config. */
  const scheduleBlock = revision ? null : (
    <>
      <SchedulePanel
        pipelineId={pipeline.id}
        pipelineParams={pipeline.params}
        pipelineType={pipeline.pipeline_type}
      />
      {/* Who hears about a run — its own panel, not part of the schedule:
          manual runs notify too (plan 070). */}
      <NotificationsPanel pipelineId={pipeline.id} />
    </>
  );

  /* No preview rail on a revision. Preview compiles the *saved* pipeline, so
     showing it beside a historical spec would report results the spec on
     screen did not produce. The revision's YAML and diff take the slot. */
  const rail = revision ? (
    <RevisionYaml revision={revision} />
  ) : (
    <Rail
      pipeline={pipeline}
      activeRunId={activeRunId}
      onDismissRun={() => setActiveRunId(null)}
      showPreview={!quality}
    />
  );

  return (
    <SchemaProvider>
      <PipelineParamsProvider params={pipeline.params}>
        <AutoInferSchemas sources={pipeline.sources ?? []} />
        <AutoStepSchemas pipeline={pipeline} />

        <Topbar
          crumbs={[
            { label: "DTE Pipelines", href: "/pipelines" },
            revision
              ? {
                  label: pipeline.name,
                  href: `/pipelines/detail?id=${encodeURIComponent(pipeline.id)}`,
                }
              : { label: pipeline.name },
            ...(revision ? [{ label: revision.id.slice(0, 8) }] : []),
          ]}
          actions={
            revision ? (
              <Link href={`/pipelines/detail?id=${encodeURIComponent(pipeline.id)}`}>
                <Button size="sm">Back to current</Button>
              </Link>
            ) : (
              <>
                {dirty && (
                  <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-gold">
                    unsaved
                  </span>
                )}
                {canEdit && (
                  <Button
                    variant={dirty ? "primary" : "default"}
                    size="sm"
                    onClick={save}
                    disabled={saving || !dirty}
                  >
                    {saving ? "Saving…" : "Save"}
                  </Button>
                )}
                <CompareButton pipeline={pipeline} onMatrixChange={(matrix) => patch({ matrix })} />
                <TriggerRunButton
                  pipeline={pipeline}
                  variant="primary"
                  onStarted={setActiveRunId}
                />
              </>
            )
          }
        />

        <PageHeader
          title={pipeline.name}
          sub={quality ? "quality" : "transform"}
          lede={pipelineShape(pipeline)}
        />

        {revision && (
          <div className="px-14 py-2.5 border-b border-border bg-[color:var(--accent-tint)] flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent">
              read-only revision
            </span>
            <span className="font-mono text-[11.5px] text-muted">{revision.id.slice(0, 8)}</span>
            <span className="text-[12px] text-subtle">
              {revision.summary ?? "initial revision"}
              {revision.changed_at && ` · ${new Date(revision.changed_at).toLocaleString()}`}
              {revision.changed_by && ` · ${revision.changed_by}`}
            </span>
          </div>
        )}

        {/* Sticky at the Topbar's 52px so the tabs — and the last-run health
            they carry — stay reachable however far down a long pipeline you
            have scrolled. 52 + 48 = the rail's 100px offset below.
            Hidden on a revision: runs and history belong to the pipeline as
            it stands, not to a frozen copy of it. */}
        {!revision && (
          <div className="sticky top-[52px] z-10 bg-surface border-b border-border px-14">
            <Tabs
              options={[
                { value: "spec", label: quality ? "Checks" : "Spec" },
                {
                  value: "runs",
                  label: "Runs",
                  badge: lastRun ? (
                    <RunTone run={lastRun}>{runOutcome(lastRun, quality)}</RunTone>
                  ) : (
                    "never run"
                  ),
                },
                { value: "history", label: "History" },
                /* Only where a comparison is possible — the same `structure`
                 step gate Compare… uses. A tab present on every pipeline
                 that can never have one is the noise the rail panel avoided
                 by rendering null, and a tab cannot render null. */
                ...(comparable
                  ? [
                      {
                        value: "comparisons" as const,
                        label: "Comparisons",
                        ...(comparisonCount > 0 ? { badge: comparisonCount } : {}),
                      },
                    ]
                  : []),
              ]}
              value={view}
              onChange={changeView}
              className="max-w-md border-b-0"
            />
          </div>
        )}

        {view === "spec" && (
          /* Rail width, and why it differs by pipeline type.
             Usable spec width is roughly `viewport − 260 sidebar − 112 inset
             − 24 gap − rail`, so at 1440 the spec column is `1044 − rail`.

             The ~620px floor that pinned this at 340px comes from the **rules
             rows**, and those only exist on a quality pipeline — which never
             renders the preview (`showPreview={!quality}`). The constraint and
             the thing needing room are on mutually exclusive pages, so they
             get different tracks:

               quality      xl 420  2xl 480   → 624px spec at 1440, the floor
               everything   xl 560  2xl 680   → 484px spec at 1440

             The non-quality track is now taking real width off the step
             editors — 484px at 1440, 464px at 1280. That is close to their
             limit: below ~450px the Filter editor's Basic rows and the
             Rename pairs start wrapping. If the preview still needs more
             room, the answer is no longer this number — it is giving the
             preview its own full-width surface, not shrinking the spec
             further.

             340px was too narrow for the preview's own table — sample rows
             wrapped into unreadable columns. Widen the quality track only by
             raising the breakpoint, never by cutting into its xl figure. */
          <div
            className={cn(
              "px-14 py-8 grid grid-cols-1 gap-6 items-start",
              rail &&
                (revision
                  ? /* Read-only spec beside a two-column diff: the diff needs
                       the width more than display-only editors do. */
                    "xl:grid-cols-2"
                  : quality
                    ? "xl:grid-cols-[1fr_420px] 2xl:grid-cols-[1fr_480px]"
                    : "xl:grid-cols-[1fr_560px] 2xl:grid-cols-[1fr_680px]"),
            )}
          >
            <div className="space-y-5 min-w-0">
              {/* Endpoints stacked at the top, source then destination.
                  They are the pipeline's contract — read together, changed
                  together — and burying the destination under the steps meant
                  scrolling the whole body to answer "where does this land?".
                  At 300 steps that answer was thousands of pixels away.
                  Vertical rather than side by side because both are
                  full-width forms, and reading down keeps the in → out
                  direction the steps below continue. */}
              {identityBlock}
              {sourcesBlock}
              {outputBlock}
              {inputsBlock}
              {scheduleBlock}
              {stepsBlock}
              {settingsBlock}
            </div>
            {rail && <div className="min-w-0 xl:sticky xl:top-[100px]">{rail}</div>}
          </div>
        )}

        {view === "runs" && (
          <div className="px-14 py-8">
            <RunsPane pipelineId={pipeline.id} />
          </div>
        )}

        {view === "history" && (
          <div className="px-14 py-8">
            <HistoryPane pipelineId={pipeline.id} />
          </div>
        )}

        {view === "comparisons" && (
          <div className="px-14 py-8">
            <ComparisonsPane pipelineId={pipeline.id} />
          </div>
        )}
      </PipelineParamsProvider>
    </SchemaProvider>
  );
}
