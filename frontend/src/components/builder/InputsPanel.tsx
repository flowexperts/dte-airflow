"use client";

import { Button, Dropdown, Field, Input, Panel, PanelHead } from "@/components/ui";
import type { ParamType, PipelineParam } from "@/lib/api";
import { compatibleFor, type SystemVar } from "@/lib/system-vars";
import { cn } from "@/lib/cn";

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
      { name: "", type: "string", required: true, default: null, description: null },
    ]);

  return (
    <Panel>
      <PanelHead label="Inputs" count={params.length} />
      <div className="@container px-4 py-3 space-y-3">
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
            /* Stacked card below 720px; the original single row above it. The
               6-column form needs ~820px and was overflowing a Panel that
               clips (overflow-hidden), so the tail simply vanished. */
            className={cn(
              "relative grid grid-cols-2 gap-2 items-end",
              "rounded-[var(--radius)] border border-border p-2.5",
              "@[720px]:grid-cols-[1.2fr_120px_90px_1.2fr_1.5fr_28px]",
              "@[720px]:border-0 @[720px]:p-0 @[720px]:rounded-none",
            )}
          >
            {/* Pinned to the card corner while stacked, so it costs no grid
                row — as a row it left a 30px empty band above the first
                field. Rejoins the trailing 28px column once the row unstacks. */}
            <button
              type="button"
              onClick={() => remove(i)}
              className={cn(
                "absolute right-2 top-2 z-10 leading-none text-subtle hover:text-red text-sm",
                "@[720px]:static @[720px]:order-last @[720px]:col-span-1",
                "@[720px]:justify-self-end @[720px]:h-[30px]",
              )}
              aria-label="Remove input"
            >
              ×
            </button>
            <Field label="Name" className="col-span-2 @[720px]:col-span-1">
              <Input
                value={p.name}
                onChange={(e) => update(i, { name: e.target.value })}
                placeholder="start_date"
              />
            </Field>
            <Field label="Type">
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
            <Field label="Required">
              <label className="inline-flex items-center gap-1.5 text-[12.5px] text-muted">
                <input
                  type="checkbox"
                  checked={p.required ?? true}
                  onChange={(e) => update(i, { required: e.target.checked })}
                />
                required
              </label>
            </Field>
            <Field label="Default" className="col-span-2 @[720px]:col-span-1">
              {(() => {
                const dynOpts = compatibleFor(p.type);
                const raw = p.default ?? "";
                const m = raw.match(/^\{\{\s*([\w.]+)\s*\}\}$/);
                const isDyn = !!m && dynOpts.length > 0;
                if (!isDyn) {
                  return (
                    <Input
                      value={raw}
                      onChange={(e) =>
                        update(i, {
                          default: e.target.value === "" ? null : e.target.value,
                        })
                      }
                      placeholder={dynOpts.length > 0 ? "value or {{today}}" : "optional"}
                      list={dynOpts.length > 0 ? `sysvars-${i}` : undefined}
                    />
                  );
                }
                return (
                  <Dropdown<SystemVar>
                    value={m![1] as SystemVar}
                    onChange={(v) => update(i, { default: `{{${v}}}` })}
                    options={dynOpts.map((v) => ({
                      value: v,
                      label: <span className="font-mono">{`{{${v}}}`}</span>,
                      meta: "dynamic",
                    }))}
                  />
                );
              })()}
              {compatibleFor(p.type).length > 0 && (
                <datalist id={`sysvars-${i}`}>
                  {compatibleFor(p.type).map((v) => (
                    <option key={v} value={`{{${v}}}`} label={`${v} · dynamic`} />
                  ))}
                </datalist>
              )}
            </Field>
            <Field label="Description" className="col-span-2 @[720px]:col-span-1">
              <Input
                value={p.description ?? ""}
                onChange={(e) =>
                  update(i, { description: e.target.value === "" ? null : e.target.value })
                }
                placeholder="what this input controls"
              />
            </Field>
          </div>
        ))}
        <Button variant="ghost" size="sm" onClick={add}>
          + Add input
        </Button>
      </div>
    </Panel>
  );
}
