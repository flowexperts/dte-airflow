"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Button, Field, Input, PageHeader, Topbar } from "@/components/ui";
import {
  createPipeline,
  updatePipeline,
  type Pipeline,
} from "@/lib/api";
import { SourcesPanel } from "./sources";
import { StepsPanel } from "./steps/StepsPanel";
import type { StepShape } from "./steps/types";
import { DestinationPicker } from "./DestinationPicker";
import { SchemaProvider, useSchemas } from "./schema-context";
import { validateField, validatePipelineForm } from "@/lib/validation";

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

export function BuilderForm({
  initial,
  mode,
  preview,
}: {
  initial: Pipeline;
  mode: "create" | "edit";
  preview?: ReactNode;
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

  const save = async () => {
    const errors = validatePipelineForm({
      id: pipeline.id,
      name: pipeline.name,
      sources: pipeline.sources ?? [],
      output_id: pipeline.output_id ?? "",
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
      if (mode === "create") {
        await createPipeline(pipeline);
      } else {
        await updatePipeline(pipeline.id, pipeline);
      }
      router.push(`/pipelines/${encodeURIComponent(pipeline.id)}`);
    } catch (e) {
      setSubmitErr(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };

  // Shared field grid used in both the split-pane and single-column layouts.
  const fieldGrid = (
    <div className="grid grid-cols-2 gap-3">
      <Field
        label="Pipeline id"
        hint="stable identifier; can't change after create"
        error={fieldErrors.id}
      >
        <Input
          value={pipeline.id}
          onChange={(e) => {
            setPipeline({ ...pipeline, id: e.target.value });
            revalidateField("id", e.target.value);
          }}
          onBlur={(e) => touchField("id", e.target.value)}
          disabled={mode === "edit"}
        />
      </Field>
      <Field label="Name" error={fieldErrors.name}>
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
    </div>
  );

  return (
    <SchemaProvider>
      <AutoInferSchemas sourceIds={pipeline.sources ?? []} />
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

      {preview ? (
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
              <DestinationPicker
                outputId={pipeline.output_id ?? ""}
                onChange={(output_id) => {
                  setPipeline({ ...pipeline, output_id });
                  touchField("output_id", output_id);
                }}
                error={fieldErrors.output_id}
              />
              <StepsPanel
                steps={(pipeline.steps ?? []) as StepShape[]}
                onChange={(steps) => setPipeline({ ...pipeline, steps })}
              />
            </div>
          </div>
          <div className="overflow-y-auto hidden lg:block">
            <div className="px-8 py-8">{preview}</div>
          </div>
        </div>
      ) : (
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

          <DestinationPicker
            outputId={pipeline.output_id ?? ""}
            onChange={(output_id) => {
              setPipeline({ ...pipeline, output_id });
              touchField("output_id", output_id);
            }}
            error={fieldErrors.output_id}
          />

          <StepsPanel
            steps={(pipeline.steps ?? []) as StepShape[]}
            onChange={(steps) => setPipeline({ ...pipeline, steps })}
          />
        </div>
      )}
    </SchemaProvider>
  );
}
