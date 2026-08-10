"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
import type { StepShape } from "@/components/builder/steps/types";
import {
  updatePipeline,
  type Destination,
  type Pipeline,
  type PipelineRevision,
  type Source,
} from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { usePermissions } from "@/lib/use-permissions";
import { cn } from "@/lib/cn";
import { AutoInferSchemas, AutoStepSchemas } from "./schema-sync";
import { TriggerRunButton } from "./trigger";
import {
  RunTone,
  destinationPathLabel,
  pipelineShape,
  runOutcome,
  sourcePathLabel,
} from "./helpers";
import { StepsColumn } from "./steps-column";
import { Rail } from "./rail";
import { HistoryPane, RunsPane, usePipelineRuns } from "./activity";

type PipelineView = "spec" | "runs" | "history";

/** Read-only sources, for viewers without write permission. */
function SourcesCard({
  sources,
  ids,
}: {
  sources: (Source | null)[];
  ids: string[];
}) {
  return (
    <Panel>
      <PanelHead label="Sources" count={ids.length} />
      {ids.length === 0 && (
        <div className="px-4 py-4 text-sm text-subtle">No sources.</div>
      )}
      {sources.map((s, i) =>
        s ? (
          <Item
            key={s.id}
            glyph="§"
            label={s.id}
            path={sourcePathLabel(s)}
            tag={<Tag>{s.source_type}</Tag>}
          />
        ) : (
          <Item
            key={ids[i] ?? i}
            glyph="§"
            label={ids[i] ?? "?"}
            path="(source not found)"
            tag={<Tag>missing</Tag>}
          />
        ),
      )}
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
  const [view, setView] = useState<PipelineView>("spec");

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
    <SourcesPanel
      sources={pipeline.sources ?? []}
      onChange={(next) => patch({ sources: next })}
    />
  ) : (
    <SourcesCard sources={sources} ids={pipeline.sources ?? []} />
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
      pipelineType={quality ? "quality" : "transform"}
      openIndex={openStep}
      onOpenChange={setOpenStep}
      readOnly={!canEdit}
    />
  );

  /* Name and inputs are real but rarely-touched. Behind a disclosure so they
   * don't push the steps — the thing you came to change — down the page. */
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
            Settings
          </span>
        </span>
        <span className="text-xs text-subtle">
          name · {(pipeline.params ?? []).length} input
          {(pipeline.params ?? []).length === 1 ? "" : "s"}
        </span>
      </button>
      {settingsOpen && (
        <div className="border-t border-border px-3.5 py-3.5 space-y-4">
          {canEdit ? (
            <Field label="Name" hint="editable; unique per workspace">
              <Input
                value={pipeline.name}
                onChange={(e) => patch({ name: e.target.value })}
              />
            </Field>
          ) : (
            <Field label="Name">
              <span className="text-[13px] text-muted">{pipeline.name}</span>
            </Field>
          )}
          <div className="font-mono text-[11px] text-subtle">id: {pipeline.id}</div>
          <div className="font-mono text-[11px] text-subtle">
            type: {quality ? "quality" : "transform"}
          </div>
          {canEdit && (
            <InputsPanel
              params={pipeline.params ?? []}
              onChange={(params) => patch({ params })}
            />
          )}
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
   * Hidden on a revision: schedules are not versioned, so showing one beside
   * a historical spec would imply a cadence that spec never carried. */
  const scheduleBlock = revision ? null : (
    <SchedulePanel pipelineId={pipeline.id} pipelineParams={pipeline.params} />
  );

  /* No rail on a revision. Preview compiles the *saved* pipeline, so showing
     it beside a historical spec would report results the spec on screen did
     not produce. */
  const rail = revision ? null : (
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
        <AutoInferSchemas sourceIds={pipeline.sources ?? []} />
        <AutoStepSchemas pipeline={pipeline} />

        <Topbar
          crumbs={[
            { label: "Workspace", href: "/" },
            { label: "Pipelines", href: "/pipelines" },
            revision
              ? { label: pipeline.name, href: `/pipelines/${encodeURIComponent(pipeline.id)}` }
              : { label: pipeline.name },
            ...(revision ? [{ label: revision.id.slice(0, 8) }] : []),
          ]}
          actions={
            revision ? (
              <Link href={`/pipelines/${encodeURIComponent(pipeline.id)}`}>
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
            <span className="font-mono text-[11.5px] text-muted">
              {revision.id.slice(0, 8)}
            </span>
            <span className="text-[12px] text-subtle">
              {revision.summary ?? "initial revision"}
              {revision.changed_at &&
                ` · ${new Date(revision.changed_at).toLocaleString()}`}
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
            ]}
            value={view}
            onChange={setView}
            className="max-w-md border-b-0"
          />
        </div>
        )}

        {view === "spec" && (
          /* Every step editor is open, so the spec column always needs the
             room: the rules rows want ~620px and an even split gives ~536px.
             A fixed 340px rail keeps the live preview on screen while leaving
             ~700px at 1440 and ~1160px at 1920. */
          <div
            className={cn(
              "px-14 py-8 grid grid-cols-1 gap-6 items-start",
              rail && "xl:grid-cols-[1fr_340px]",
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
              {sourcesBlock}
              {outputBlock}
              {scheduleBlock}
              {stepsBlock}
              {settingsBlock}
            </div>
            {rail && (
              <div className="min-w-0 xl:sticky xl:top-[100px]">{rail}</div>
            )}
          </div>
        )}

        {view === "runs" && (
          <div className="px-14 py-8">
            <RunsPane runs={runs} />
          </div>
        )}

        {view === "history" && (
          <div className="px-14 py-8">
            <HistoryPane pipelineId={pipeline.id} />
          </div>
        )}

      </PipelineParamsProvider>
    </SchemaProvider>
  );
}
