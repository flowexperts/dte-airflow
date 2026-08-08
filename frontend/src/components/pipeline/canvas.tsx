"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Button,
  Field,
  Input,
  Item,
  PageHeader,
  Panel,
  PanelHead,
  Tag,
  Topbar,
} from "@/components/ui";
import { SchemaProvider } from "@/components/builder/schema-context";
import { PipelineParamsProvider } from "@/components/builder/params-context";
import { SourcesPanel } from "@/components/builder/sources";
import { DestinationPicker } from "@/components/builder/DestinationPicker";
import { InputsPanel } from "@/components/builder/InputsPanel";
import type { StepShape } from "@/components/builder/steps/types";
import {
  updatePipeline,
  type Destination,
  type Pipeline,
  type Source,
} from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { usePermissions } from "@/lib/use-permissions";
import { cn } from "@/lib/cn";
import { AutoInferSchemas, AutoStepSchemas } from "./schema-sync";
import { TriggerRunButton } from "./trigger";
import {
  destinationPathLabel,
  pipelineShape,
  sourcePathLabel,
} from "./helpers";
import { StepsColumn } from "./steps-column";
import { Rail } from "./rail";

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
}: {
  initialPipeline: Pipeline;
  sources: (Source | null)[];
  destination: Destination | null;
}) {
  const router = useRouter();
  const toast = useToast();
  const { can } = usePermissions();
  const canEdit = can("pipeline:write");

  const [pipeline, setPipeline] = useState<Pipeline>(initialPipeline);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [openStep, setOpenStep] = useState<number | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

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

  const rail = (
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
            { label: pipeline.name },
          ]}
          actions={
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
          }
        />

        <PageHeader
          title={pipeline.name}
          sub={quality ? "quality" : "transform"}
          lede={pipelineShape(pipeline)}
        />

        {/* The rail yields width while a step is open. The editors need ~620px
            for their rules rows and only get ~536px at an even split — but
            hiding the rail outright would take the live preview away at exactly
            the moment you're changing a filter and want to see its effect. */}
        <div
          className={cn(
            "px-14 py-8 grid grid-cols-1 gap-6 items-start",
            "transition-[grid-template-columns] duration-200",
            openStep === null
              ? "xl:grid-cols-[1.25fr_1fr]"
              : "xl:grid-cols-[1fr_340px]",
          )}
        >
          <div className="space-y-5 min-w-0">
            {sourcesBlock}
            {stepsBlock}
            {outputBlock}
            {settingsBlock}
          </div>
          <div className="min-w-0 xl:sticky xl:top-[100px]">{rail}</div>
        </div>

      </PipelineParamsProvider>
    </SchemaProvider>
  );
}
