"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Button,
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
    value: "a" as const,
    label: "Canvas",
    note: "Spec on the left, run and preview on the right. Edit in place.",
  },
  {
    value: "b" as const,
    label: "Console",
    note: "Outline · focused node · rail. Never scrolls the spec.",
  },
  {
    value: "c" as const,
    label: "Ribbon",
    note: "Flow across the top as the navigation; selected node below.",
  },
];

function SourcesCard({ sources, ids }: { sources: (Source | null)[]; ids: string[] }) {
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
 * Output card — or, for a quality pipeline, the thing that actually belongs
 * here. The current detail page renders "Output → (destination not found)" for
 * every quality pipeline, which is worse than showing nothing.
 */
function OutputCard({
  pipeline,
  destination,
}: {
  pipeline: Pipeline;
  destination: Destination | null;
}) {
  if (pipeline.pipeline_type === "quality") {
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

  return (
    <Panel>
      <PanelHead label="Output" count={1} />
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

/** Shared node list for variants B and C. */
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
      label: pipeline.pipeline_type === "quality" ? "Report" : "Output",
      detail: pipeline.output_id || "—",
    },
  ];
}

export function LabPipelineDetail({
  initialPipeline,
  sources,
  destination,
  variant,
  initialEdit,
}: {
  initialPipeline: Pipeline;
  sources: (Source | null)[];
  destination: Destination | null;
  variant: Variant;
  initialEdit: boolean;
}) {
  const router = useRouter();
  const toast = useToast();
  const { can } = usePermissions();
  const canEdit = can("pipeline:write");

  const [pipeline, setPipeline] = useState<Pipeline>(initialPipeline);
  const [editing, setEditing] = useState(initialEdit && canEdit);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [openStep, setOpenStep] = useState<number | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string>("sources");

  const steps = (pipeline.steps ?? []) as StepShape[];
  const quality = pipeline.pipeline_type === "quality";
  const readOnly = !editing;

  const setSteps = (next: StepShape[]) => {
    setPipeline((p) => ({ ...p, steps: next as Pipeline["steps"] }));
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

  const stepsColumn = (
    <StepsColumn
      steps={steps}
      onChange={setSteps}
      pipelineType={quality ? "quality" : "transform"}
      openIndex={openStep}
      onOpenChange={setOpenStep}
      readOnly={readOnly}
    />
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

  /** Variants B and C show one node at a time; A shows the whole spec. */
  const focusedNode = () => {
    if (selectedNode === "sources") {
      return <SourcesCard sources={sources} ids={pipeline.sources ?? []} />;
    }
    if (selectedNode === "output") {
      return <OutputCard pipeline={pipeline} destination={destination} />;
    }
    return stepsColumn;
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
                  size="sm"
                  onClick={() => {
                    setEditing((v) => !v);
                    setOpenStep(null);
                  }}
                >
                  {editing ? "Done editing" : "Edit"}
                </Button>
              )}
              {dirty && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={save}
                  disabled={saving}
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
              <SourcesCard sources={sources} ids={pipeline.sources ?? []} />
              {stepsColumn}
              <OutputCard pipeline={pipeline} destination={destination} />
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
                  onClick={() => {
                    setSelectedNode(n.key);
                    const m = /^step-(\d+)$/.exec(n.key);
                    setOpenStep(m?.[1] ? Number(m[1]) : null);
                  }}
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
            <div className="min-w-0">{focusedNode()}</div>
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
                      onClick={() => {
                        setSelectedNode(n.key);
                        const m = /^step-(\d+)$/.exec(n.key);
                        setOpenStep(m?.[1] ? Number(m[1]) : null);
                      }}
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
              <div className="min-w-0">{focusedNode()}</div>
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
