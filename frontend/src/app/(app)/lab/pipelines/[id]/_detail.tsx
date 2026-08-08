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
  Tag,
  Topbar,
} from "@/components/ui";
import { SchemaProvider } from "@/components/builder/schema-context";
import { PipelineParamsProvider } from "@/components/builder/params-context";
import { HistoryPanel } from "@/components/builder/history/HistoryPanel";
import { SourcesPanel } from "@/components/builder/sources";
import { DestinationPicker } from "@/components/builder/DestinationPicker";
import { InputsPanel } from "@/components/builder/InputsPanel";
import type { StepShape } from "@/components/builder/steps/types";
import { labelFor } from "@/components/builder/steps/types";
import { stepTitle } from "@/components/builder/steps/summary";
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
import { AutoInferSchemas, AutoStepSchemas } from "../../_schema-sync";
import { LabTriggerButton } from "../../_trigger";
import { VariantBar } from "../../_variant";
import type { Variant, VariantOption } from "../../_variant-util";
import {
  destinationPathLabel,
  pipelineShape,
  sourcePathLabel,
} from "../../_lib";
import { StepsColumn } from "./_steps-column";
import { Rail } from "./_rail";

const OPTIONS: VariantOption[] = [
  {
    value: "a",
    label: "Canvas",
    note: "Spec on the left, run and preview on the right. Everything edits in place.",
  },
  {
    value: "b",
    label: "Console",
    note: "Outline · focused node · rail. Never scrolls the spec.",
  },
  {
    value: "c",
    label: "Ribbon",
    note: "Flow across the top as the navigation; selected node below.",
  },
];

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

function nodeList(pipeline: Pipeline) {
  const steps = (pipeline.steps ?? []) as StepShape[];
  return [
    { key: "sources", label: "Sources", detail: `${pipeline.sources?.length ?? 0}` },
    ...steps.map((s, i) => ({
      key: `step-${i}`,
      label: labelFor(s),
      detail: stepTitle(s),
    })),
    {
      key: "output",
      label: pipeline.pipeline_type === "quality" ? "Report" : "Destination",
      detail: pipeline.output_id || "—",
    },
  ];
}

export function LabPipelineDetail({
  initialPipeline,
  sources,
  destination,
  variant,
}: {
  initialPipeline: Pipeline;
  sources: (Source | null)[];
  destination: Destination | null;
  variant: Variant;
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
  const [selectedNode, setSelectedNode] = useState<string>("sources");
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

  const nodes = nodeList(pipeline);

  const selectNode = (key: string) => {
    setSelectedNode(key);
    const m = /^step-(\d+)$/.exec(key);
    setOpenStep(m?.[1] ? Number(m[1]) : null);
  };

  const focusedNode = () => {
    if (selectedNode === "sources") return sourcesBlock;
    if (selectedNode === "output") return outputBlock;
    return stepsBlock;
  };

  return (
    <SchemaProvider>
      <PipelineParamsProvider params={pipeline.params}>
        <AutoInferSchemas sourceIds={pipeline.sources ?? []} />
        <AutoStepSchemas pipeline={pipeline} />

        <Topbar
          crumbs={[
            { label: "Workspace", href: "/" },
            { label: "Lab", href: "/lab" },
            { label: "Pipelines", href: "/lab/pipelines" },
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
              <LabTriggerButton
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

        <VariantBar options={OPTIONS} current={variant} />

        {/* ---------------- A · canvas ---------------- */}
        {variant === "a" && (
          <div className="px-14 py-8 grid grid-cols-1 xl:grid-cols-[1.25fr_1fr] gap-6 items-start">
            <div className="space-y-5 min-w-0">
              {sourcesBlock}
              {stepsBlock}
              {outputBlock}
              {settingsBlock}
            </div>
            <div className="min-w-0 xl:sticky xl:top-[100px] space-y-5">
              {rail}
              <Panel>
                <PanelHead label="History" />
                <div className="px-1.5 py-1.5">
                  <HistoryPanel pipelineId={pipeline.id} />
                </div>
              </Panel>
            </div>
          </div>
        )}

        {/* ---------------- B · console ---------------- */}
        {variant === "b" && (
          <div className="px-14 py-8 grid grid-cols-1 lg:grid-cols-[210px_1fr] xl:grid-cols-[210px_1fr_360px] gap-6 items-start">
            <Panel className="lg:sticky lg:top-[100px]">
              <PanelHead label="Outline" count={nodes.length} />
              {nodes.map((n) => (
                <button
                  key={n.key}
                  type="button"
                  onClick={() => selectNode(n.key)}
                  className={cn(
                    "w-full text-left px-3.5 py-2 border-b border-border last:border-b-0 transition-colors",
                    selectedNode === n.key
                      ? "bg-[color:var(--accent-tint)]"
                      : "hover:bg-hover",
                  )}
                >
                  <div
                    className={cn(
                      "font-mono text-[10px] tracking-[0.15em] uppercase",
                      selectedNode === n.key ? "text-accent" : "text-subtle",
                    )}
                  >
                    {n.label}
                  </div>
                  <div className="text-[12px] text-muted truncate">{n.detail}</div>
                </button>
              ))}
            </Panel>
            <div className="min-w-0 space-y-5">
              {focusedNode()}
              {settingsBlock}
            </div>
            <div className="min-w-0 xl:sticky xl:top-[100px]">{rail}</div>
          </div>
        )}

        {/* ---------------- C · ribbon ---------------- */}
        {variant === "c" && (
          <div className="px-14 py-8 space-y-6">
            <div className="overflow-x-auto pb-1">
              <div className="flex items-stretch gap-2 min-w-max">
                {nodes.map((n, i) => (
                  <div key={n.key} className="flex items-center gap-2">
                    {i > 0 && <span className="text-subtle text-sm">→</span>}
                    <button
                      type="button"
                      onClick={() => selectNode(n.key)}
                      className={cn(
                        "min-w-[150px] max-w-[220px] text-left px-3 py-2.5 rounded-[var(--radius)] border transition-colors",
                        selectedNode === n.key
                          ? "border-accent bg-[color:var(--accent-tint)]"
                          : "border-border bg-surface hover:border-border-2",
                      )}
                    >
                      <div
                        className={cn(
                          "font-mono text-[10px] tracking-[0.15em] uppercase",
                          selectedNode === n.key ? "text-accent" : "text-subtle",
                        )}
                      >
                        {n.label}
                      </div>
                      <div className="text-[12.5px] text-text truncate mt-0.5">
                        {n.detail}
                      </div>
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-6 items-start">
              <div className="min-w-0 space-y-5">
                {focusedNode()}
                {settingsBlock}
              </div>
              <div className="min-w-0 xl:sticky xl:top-[100px]">{rail}</div>
            </div>
          </div>
        )}

        <div className="px-14 pb-8">
          <Link
            href={`/pipelines/${encodeURIComponent(pipeline.id)}`}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle no-underline hover:text-text"
          >
            ← compare with the current page
          </Link>
        </div>
      </PipelineParamsProvider>
    </SchemaProvider>
  );
}
