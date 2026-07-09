"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Field, Input, PageHeader, Topbar } from "@/components/ui";
import {
  createPipeline,
  isJsonFileOutput,
  updatePipeline,
  type JsonFileOutput,
  type Pipeline,
} from "@/lib/api";
import { SourcesPanel } from "./sources";
import { StepsPanel } from "./steps/StepsPanel";
import type { StepShape } from "./steps/types";
import { OutputPanel } from "./OutputPanel";
import { SchemaProvider } from "./schema-context";

export function BuilderForm({
  initial,
  mode,
}: {
  initial: Pipeline;
  mode: "create" | "edit";
}) {
  const router = useRouter();
  const [pipeline, setPipeline] = useState<Pipeline>(initial);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const validate = (): string | null => {
    const id = pipeline.id.trim();
    if (!id) return "Pipeline id is required.";
    if (!/^[a-zA-Z0-9_-]+$/.test(id))
      return "Pipeline id may only contain letters, numbers, '_' and '-'.";
    if (!pipeline.name.trim()) return "Pipeline name is required.";
    const path = "path" in pipeline.output ? pipeline.output.path : "";
    if (!path?.trim()) return "Output path is required.";
    for (const [i, step] of (pipeline.steps ?? []).entries()) {
      const s = step as { op?: string; fields?: unknown[] };
      if (s.op === "select" && (!s.fields || s.fields.length === 0)) {
        return `Step ${i + 1} (select) needs at least one field. Pick one, drop the step, or switch back to "Keep all" by removing the step.`;
      }
    }
    return null;
  };

  const save = async () => {
    const problem = validate();
    if (problem) {
      setErr(problem);
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      if (mode === "create") {
        await createPipeline(pipeline);
      } else {
        await updatePipeline(pipeline.id, pipeline);
      }
      router.push(`/pipelines/${encodeURIComponent(pipeline.id)}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };

  return (
    <SchemaProvider>
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

      <div className="px-14 py-8 space-y-6">
        {err && (
          <div className="p-3 border border-red rounded bg-code-bg text-red font-mono text-[12.5px]">
            {err}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="Pipeline id" hint="stable identifier; can't change after create">
            <Input
              value={pipeline.id}
              onChange={(e) => setPipeline({ ...pipeline, id: e.target.value })}
              disabled={mode === "edit"}
            />
          </Field>
          <Field label="Name">
            <Input
              value={pipeline.name}
              onChange={(e) => setPipeline({ ...pipeline, name: e.target.value })}
              placeholder="Orders — nightly cohort"
            />
          </Field>
        </div>

        <SourcesPanel
          sources={pipeline.sources ?? []}
          onChange={(sources) => setPipeline({ ...pipeline, sources })}
        />

        <StepsPanel
          steps={(pipeline.steps ?? []) as StepShape[]}
          onChange={(steps) => setPipeline({ ...pipeline, steps })}
        />

        {isJsonFileOutput(pipeline.output) ? (
          <OutputPanel
            output={pipeline.output}
            onChange={(output: JsonFileOutput) =>
              setPipeline({ ...pipeline, output })
            }
          />
        ) : (
          <div className="border border-border rounded p-4 text-sm text-subtle bg-surface">
            This pipeline uses a {pipeline.output.type} output which isn&apos;t
            editable in the UI yet.
          </div>
        )}
      </div>
    </SchemaProvider>
  );
}
