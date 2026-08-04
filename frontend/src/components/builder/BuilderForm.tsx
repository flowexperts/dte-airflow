"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Button, Field, Input, PageHeader, Segmented, Topbar } from "@/components/ui";
import {
  ApiError,
  createPipeline,
  isPipelineGateError,
  pipelineStepSchemas,
  updatePipeline,
  type Pipeline,
} from "@/lib/api";
import { SourcesPanel } from "./sources";
import { StepsPanel } from "./steps/StepsPanel";
import { InputsPanel } from "./InputsPanel";
import { PipelineParamsProvider } from "./params-context";
import type { StepShape } from "./steps/types";
import { DestinationPicker } from "./DestinationPicker";
import { SchemaProvider, useSchemas } from "./schema-context";
import { PipelinePreview } from "@/components/pipeline-preview";
import { validateField, validatePipelineForm } from "@/lib/validation";

/** Turn a save error into a human-readable message. Handles the structured
 *  engine-gating 422 payloads (`engine_incompatible`, `trino_not_enabled`)
 *  by pulling the reasons out instead of dumping the raw JSON. */
function formatSaveError(e: unknown): string {
  if (e instanceof ApiError && isPipelineGateError(e.rawDetail)) {
    const d = e.rawDetail;
    if (d.code === "trino_not_enabled") {
      return d.message ||
        "Trino engine is not enabled on this deployment. Choose a different engine.";
    }
    const lines: string[] = [`Engine '${d.engine}' can't run this pipeline:`];
    for (const s of d.incompatible_sources) {
      lines.push(`  • source '${s.source_id}' (${s.connection_type}): ${s.reason}`);
    }
    if (d.incompatible_destination) {
      const x = d.incompatible_destination;
      lines.push(`  • destination '${x.destination_id}' (${x.connection_type}): ${x.reason}`);
    }
    return lines.join("\n");
  }
  return e instanceof Error ? e.message : String(e);
}


function AutoInferSchemas({ sourceIds }: { sourceIds: string[] }) {
  const { schemas, refreshById } = useSchemas();
  const inflight = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const id of sourceIds) {
      if (!id || inflight.current.has(id) || schemas[id]) continue;
      inflight.current.add(id);
      refreshById(id);
    }
  }, [sourceIds, schemas, refreshById]);
  return null;
}

/** Debounced /step-schemas fetch so downstream editors see the columns
 *  produced by earlier steps (plan 038 item 7). Runs whenever the pipeline
 *  spec changes; silently drops results on compile errors so the builder
 *  stays responsive. */
function AutoStepSchemas({ pipeline }: { pipeline: Pipeline }) {
  const { setPerStepSchemas } = useSchemas();
  const seq = useRef(0);
  const key = JSON.stringify(pipeline);
  useEffect(() => {
    if (
      !pipeline.sources ||
      pipeline.sources.length === 0 ||
      !pipeline.output_id ||
      (pipeline.steps ?? []).length === 0
    ) {
      setPerStepSchemas({});
      return;
    }
    const my = ++seq.current;
    const t = window.setTimeout(async () => {
      try {
        const res = await pipelineStepSchemas(pipeline);
        if (seq.current !== my) return;
        const numeric: Record<number, string[]> = {};
        for (const [k, v] of Object.entries(res.step_schemas)) {
          numeric[Number(k)] = v;
        }
        setPerStepSchemas(numeric);
      } catch {
        // A partially-typed pipeline compile-errors; keep the last-known
        // step schemas so autocomplete doesn't flicker.
      }
    }, 500);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` captures pipeline
  }, [key, setPerStepSchemas]);
  return null;
}

export function BuilderForm({
  initial,
  mode,
  preview,
  livePreview,
}: {
  initial: Pipeline;
  mode: "create" | "edit";
  /** Right-hand split-pane content — a static node (e.g. saved-pipeline
   *  preview keyed by id). Ignored when `livePreview` is set. */
  preview?: ReactNode;
  /** When true, BuilderForm renders `<PipelinePreview pipelineId={pipeline}>`
   *  itself, feeding the live builder state each edit (plan 038 item 6).
   *  Cannot be handled via a callback prop because server components can't
   *  pass functions across the client boundary. */
  livePreview?: boolean;
}) {
  const router = useRouter();
  const [pipeline, setPipeline] = useState<Pipeline>(initial);
  const [saving, setSaving] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  // Field-level errors: shown after blur (text inputs) or change (pickers),
  // cleared as soon as the value becomes valid.
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  /**
   * Validate a single field and show (or clear) its error.
   * Used on blur for text inputs and on change for picker fields.
   */
  const touchField = (
    field: "id" | "name" | "sources" | "output_id",
    value: unknown,
  ) => {
    const msg = validateField(field, value);
    setFieldErrors((prev) => {
      const next = { ...prev };
      if (msg) {
        next[field] = msg;
      } else {
        delete next[field];
      }
      return next;
    });
  };

  /**
   * Re-validate a field on every onChange only when an error is already
   * displayed for it — this clears the error as soon as the value becomes
   * valid without triggering errors on every keystroke before first blur.
   */
  const revalidateField = (
    field: "id" | "name" | "sources" | "output_id",
    value: unknown,
  ) => {
    setFieldErrors((prev) => {
      if (!prev[field]) return prev; // no error shown yet; wait for blur
      const msg = validateField(field, value);
      if (!msg) {
        const next = { ...prev };
        delete next[field];
        return next;
      }
      if (prev[field] === msg) return prev;
      return { ...prev, [field]: msg };
    });
  };

  const isQuality = pipeline.pipeline_type === "quality";

  const save = async () => {
    const errors = validatePipelineForm({
      id: pipeline.id,
      name: pipeline.name,
      sources: pipeline.sources ?? [],
      // Quality pipelines don't require a destination — pass a sentinel so
      // the min(1) check passes. The backend ignores output_id for quality.
      output_id: isQuality ? "__quality__" : (pipeline.output_id ?? ""),
      steps: (pipeline.steps ?? []) as unknown[],
    });

    if (Object.keys(errors).length > 0) {
      // Surface all field errors so every broken field is highlighted.
      setFieldErrors(errors);
      // Also show a top-level banner for the first error (backwards compat).
      const first = Object.values(errors)[0];
      setSubmitErr(first ?? "Please fix the errors above before saving.");
      return;
    }

    setSaving(true);
    setSubmitErr(null);
    setFieldErrors({});
    try {
      let destinationId = pipeline.id;
      if (mode === "create") {
        // Server generates the id — use the response, not the draft.
        // Strip the placeholder empty id so the backend's default_factory fires.
        const { id: _drop, ...body } = pipeline;
        const created = await createPipeline(body as Pipeline);
        destinationId = created.id;
      } else {
        await updatePipeline(pipeline.id, pipeline);
      }
      router.push(`/pipelines/${encodeURIComponent(destinationId)}`);
    } catch (e) {
      setSubmitErr(formatSaveError(e));
      setSaving(false);
    }
  };

  // Shared field grid used in both the split-pane and single-column layouts.
  const fieldGrid = (
    <div className="space-y-4">
      <div className="space-y-2">
        <Field label="Name" hint="editable; unique per workspace" error={fieldErrors.name}>
          <Input
            value={pipeline.name}
            onChange={(e) => {
              setPipeline({ ...pipeline, name: e.target.value });
              revalidateField("name", e.target.value);
            }}
            onBlur={(e) => touchField("name", e.target.value)}
            placeholder="Orders — nightly cohort"
          />
        </Field>
        {mode === "edit" && (
          <div className="text-xs text-subtle font-mono">id: {pipeline.id}</div>
        )}
      </div>
      {mode === "edit" ? (
        <Field label="Pipeline type">
          <span className="font-mono text-[12px] text-muted capitalize">
            {pipeline.pipeline_type ?? "transform"}
          </span>
        </Field>
      ) : (
        <Field label="Pipeline type" hint="Transform writes output data; Quality asserts conditions on it.">
          <Segmented<"transform" | "quality">
            options={[
              { value: "transform", label: "Transform" },
              { value: "quality", label: "Quality" },
            ]}
            value={pipeline.pipeline_type ?? "transform"}
            onChange={(v) => setPipeline((p: Pipeline) => ({ ...p, pipeline_type: v }))}
          />
        </Field>
      )}
    </div>
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
          { label: mode === "create" ? "New" : `Edit · ${initial.name}` },
        ]}
        actions={
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.back()}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              kbd="⌘S"
              onClick={save}
              disabled={saving}
            >
              {saving ? "Saving…" : "Save pipeline"}
            </Button>
          </>
        }
      />
      <PageHeader
        title={mode === "create" ? "New pipeline" : `Editing ${initial.name}`}
        sub={mode === "edit" ? pipeline.id : undefined}
      />

      {preview || livePreview ? (() => {
        const previewNode = livePreview
          ? <PipelinePreview pipelineId={pipeline} />
          : preview;
        return (
        <div
          className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] overflow-hidden"
          style={{ height: "calc(100vh - 52px - 89px)" }}
        >
          <div className="overflow-y-auto border-r border-border">
            <div className="px-8 py-8 space-y-6">
              {submitErr && (
                <div className="p-3 border border-red rounded bg-code-bg text-red font-mono text-[12.5px]">
                  {submitErr}
                </div>
              )}
              {fieldGrid}
              <SourcesPanel
                sources={pipeline.sources ?? []}
                onChange={(sources) => {
                  setPipeline({ ...pipeline, sources });
                  touchField("sources", sources);
                }}
                error={fieldErrors.sources}
              />
              {isQuality ? (
                <p className="text-muted text-sm">
                  Quality pipelines produce a quality report, not a data output.
                </p>
              ) : (
                <DestinationPicker
                  outputId={pipeline.output_id ?? ""}
                  onChange={(output_id) => {
                    setPipeline({ ...pipeline, output_id });
                    touchField("output_id", output_id);
                  }}
                  error={fieldErrors.output_id}
                />
              )}
              <InputsPanel
                params={pipeline.params ?? []}
                onChange={(params) => setPipeline({ ...pipeline, params })}
              />
              <StepsPanel
                steps={(pipeline.steps ?? []) as StepShape[]}
                onChange={(steps) => setPipeline({ ...pipeline, steps })}
                pipelineType={pipeline.pipeline_type ?? "transform"}
              />
            </div>
          </div>
          <div className="overflow-y-auto hidden lg:block">
            <div className="px-8 py-8">{previewNode}</div>
          </div>
        </div>
      );
      })() : (
        <div className="px-14 py-8 space-y-6">
          {submitErr && (
            <div className="p-3 border border-red rounded bg-code-bg text-red font-mono text-[12.5px]">
              {submitErr}
            </div>
          )}

          {fieldGrid}

          <SourcesPanel
            sources={pipeline.sources ?? []}
            onChange={(sources) => {
              setPipeline({ ...pipeline, sources });
              touchField("sources", sources);
            }}
            error={fieldErrors.sources}
          />

          {isQuality ? (
            <p className="text-muted text-sm">
              Quality pipelines produce a quality report, not a data output.
            </p>
          ) : (
            <DestinationPicker
              outputId={pipeline.output_id ?? ""}
              onChange={(output_id) => {
                setPipeline({ ...pipeline, output_id });
                touchField("output_id", output_id);
              }}
              error={fieldErrors.output_id}
            />
          )}

          <InputsPanel
            params={pipeline.params ?? []}
            onChange={(params) => setPipeline({ ...pipeline, params })}
          />

          <StepsPanel
            steps={(pipeline.steps ?? []) as StepShape[]}
            onChange={(steps) => setPipeline({ ...pipeline, steps })}
            pipelineType={pipeline.pipeline_type ?? "transform"}
          />
        </div>
      )}
     </PipelineParamsProvider>
    </SchemaProvider>
  );
}
