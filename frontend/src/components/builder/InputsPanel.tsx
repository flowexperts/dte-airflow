"use client";

import { Button, Field, Input, Panel, PanelHead } from "@/components/ui";
import type { ParamType, PipelineParam } from "@/lib/api";

const TYPES: ParamType[] = [
  "string",
  "int",
  "float",
  "date",
  "timestamp",
  "boolean",
];

/** Declares typed trigger-time inputs on a pipeline. Each row edits one
 *  `PipelineParam`; the parent owns the list and re-renders on every change.
 *
 *  Wire shape matches `PipelineBase.params` — no client-side coercion. */
export function InputsPanel({
  params,
  onChange,
}: {
  params: PipelineParam[];
  onChange: (next: PipelineParam[]) => void;
}) {
  const update = (i: number, patch: Partial<PipelineParam>) =>
    onChange(params.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  const remove = (i: number) => onChange(params.filter((_, idx) => idx !== i));
  const add = () =>
    onChange([
      ...params,
      { name: "", type: "string", required: true, default: "", description: "" },
    ]);

  return (
    <Panel>
      <PanelHead label="Inputs" count={params.length} />
      <div className="px-4 py-3 space-y-3">
        {params.length === 0 && (
          <div className="font-mono text-[11.5px] text-subtle">
            No inputs declared. Add one to reference it as{" "}
            <span className="text-gold">{"{{params.<name>}}"}</span> in filter
            or map expressions.
          </div>
        )}
        {params.map((p, i) => (
          <div
            key={i}
            className="grid grid-cols-[1.2fr_120px_90px_1.2fr_1.5fr_28px] gap-2 items-end"
          >
            <Field label={i === 0 ? "Name" : undefined}>
              <Input
                value={p.name}
                onChange={(e) => update(i, { name: e.target.value })}
                placeholder="start_date"
              />
            </Field>
            <Field label={i === 0 ? "Type" : undefined}>
              <select
                value={p.type}
                onChange={(e) => update(i, { type: e.target.value as ParamType })}
                className="w-full bg-bg border border-border rounded px-2 py-1.5 text-[12.5px] focus:outline-none focus:border-accent"
              >
                {TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={i === 0 ? "Required" : undefined}>
              <label className="inline-flex items-center gap-1.5 text-[12.5px] text-muted">
                <input
                  type="checkbox"
                  checked={p.required ?? true}
                  onChange={(e) => update(i, { required: e.target.checked })}
                />
                required
              </label>
            </Field>
            <Field label={i === 0 ? "Default" : undefined}>
              <Input
                value={p.default ?? ""}
                onChange={(e) => update(i, { default: e.target.value })}
                placeholder="optional"
              />
            </Field>
            <Field label={i === 0 ? "Description" : undefined}>
              <Input
                value={p.description ?? ""}
                onChange={(e) => update(i, { description: e.target.value })}
                placeholder="what this input controls"
              />
            </Field>
            <button
              type="button"
              onClick={() => remove(i)}
              className="text-subtle hover:text-red text-sm h-[30px]"
              aria-label="Remove input"
            >
              ×
            </button>
          </div>
        ))}
        <Button variant="ghost" size="sm" onClick={add}>
          + Add input
        </Button>
      </div>
    </Panel>
  );
}
