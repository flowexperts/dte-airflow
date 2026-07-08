"use client";

import { useEffect, useState } from "react";
import {
  Field,
  FieldPicker,
  FieldMultiSelect,
  Input,
  Textarea,
} from "@/components/ui";
import { useSchemas } from "../schema-context";
import type { StepShape } from "./types";

type Setter = (patch: Partial<StepShape>) => void;

export function FilterEditor({ step, set }: { step: StepShape; set: Setter }) {
  return (
    <Field label="Expression" hint="SQL WHERE clause (DuckDB)">
      <Textarea
        value={(step.expr as string) ?? ""}
        onChange={(e) => set({ expr: e.target.value })}
        placeholder="amount > 0 AND status = 'completed'"
      />
    </Field>
  );
}

/**
 * We keep an internal ordered list of {from, to} rows so the user can add
 * blank rows and edit incrementally. The parent step stores `mappings` as
 * a plain object; we sync in one direction from the local list.
 */
export function RenameEditor({ step, set }: { step: StepShape; set: Setter }) {
  const { allFields } = useSchemas();
  const mappings = (step.mappings as Record<string, string>) ?? {};

  const initial = () =>
    Object.entries(mappings).map(([from, to]) => ({ from, to }));

  const [rows, setRows] = useState<{ from: string; to: string }[]>(initial);

  // Re-sync if an external mapping (e.g. loading an existing pipeline) diverges.
  useEffect(() => {
    const asObj: Record<string, string> = {};
    for (const r of rows) if (r.from && r.to) asObj[r.from] = r.to;
    const same =
      Object.keys(asObj).length === Object.keys(mappings).length &&
      Object.entries(asObj).every(([k, v]) => mappings[k] === v);
    if (!same) setRows(initial());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mappings]);

  const commit = (next: { from: string; to: string }[]) => {
    setRows(next);
    const obj: Record<string, string> = {};
    for (const r of next) if (r.from && r.to) obj[r.from] = r.to;
    set({ mappings: obj });
  };

  const updateRow = (i: number, patch: Partial<{ from: string; to: string }>) =>
    commit(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const removeRow = (i: number) => commit(rows.filter((_, j) => j !== i));

  const addRow = () => commit([...rows, { from: "", to: "" }]);

  const usedFromNames = new Set(rows.map((r) => r.from));

  return (
    <Field label="Mappings" hint="rename fields — old name on the left, new on the right">
      <div className="space-y-1.5">
        {rows.map((r, i) => (
          <div
            key={i}
            className="grid grid-cols-[1fr_16px_1fr_28px] gap-2 items-center"
          >
            <FieldPicker
              value={r.from}
              onChange={(v) => updateRow(i, { from: v })}
              options={allFields.filter((f) => !usedFromNames.has(f.name) || f.name === r.from)}
              placeholder="old_name"
            />
            <span className="text-subtle text-center">→</span>
            <Input
              value={r.to}
              onChange={(e) => updateRow(i, { to: e.target.value })}
              placeholder="new_name"
            />
            <button
              type="button"
              onClick={() => removeRow(i)}
              className="text-subtle hover:text-red text-sm"
              aria-label="Remove mapping"
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={addRow}
          className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
        >
          + Add mapping
        </button>
      </div>
    </Field>
  );
}

const RETYPE_OPTIONS = ["string", "int", "float", "boolean", "date", "timestamp"];

export function RetypeEditor({ step, set }: { step: StepShape; set: Setter }) {
  const { allFields } = useSchemas();
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="Field">
        <FieldPicker
          value={(step.field as string) ?? ""}
          onChange={(v) => set({ field: v })}
          options={allFields}
        />
      </Field>
      <Field label="To type">
        <select
          value={(step.to_type as string) ?? "string"}
          onChange={(e) => set({ to_type: e.target.value })}
          className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px] focus:outline-none focus:border-accent"
        >
          {RETYPE_OPTIONS.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </Field>
    </div>
  );
}

export function MapLookupEditor({ step, set }: { step: StepShape; set: Setter }) {
  const { allFields } = useSchemas();
  const table = (step.table as Record<string, string>) ?? {};

  const initial = () =>
    Object.entries(table).map(([k, v]) => ({ k, v }));
  const [rows, setRows] = useState<{ k: string; v: string }[]>(initial);

  useEffect(() => {
    const obj: Record<string, string> = {};
    for (const r of rows) if (r.k) obj[r.k] = r.v;
    const same =
      Object.keys(obj).length === Object.keys(table).length &&
      Object.entries(obj).every(([k, v]) => table[k] === v);
    if (!same) setRows(initial());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table]);

  const commit = (next: { k: string; v: string }[]) => {
    setRows(next);
    const obj: Record<string, string> = {};
    for (const r of next) if (r.k) obj[r.k] = r.v;
    set({ table: obj });
  };
  const updateRow = (i: number, patch: Partial<{ k: string; v: string }>) =>
    commit(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const removeRow = (i: number) => commit(rows.filter((_, j) => j !== i));
  const addRow = () => commit([...rows, { k: "", v: "" }]);
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Field">
          <FieldPicker
            value={(step.field as string) ?? ""}
            onChange={(v) => set({ field: v })}
            options={allFields}
          />
        </Field>
        <Field label="Default" hint="value used when no match">
          <Input
            value={(step.default as string) ?? ""}
            onChange={(e) => set({ default: e.target.value || null })}
            placeholder="OTHER"
          />
        </Field>
      </div>
      <Field label="Lookup table" hint="key on the left, replacement value on the right">
        <div className="space-y-1.5">
          {rows.map((r, i) => (
            <div
              key={i}
              className="grid grid-cols-[1fr_16px_1fr_28px] gap-2 items-center"
            >
              <Input
                value={r.k}
                onChange={(e) => updateRow(i, { k: e.target.value })}
                placeholder="US"
              />
              <span className="text-subtle text-center">=</span>
              <Input
                value={r.v}
                onChange={(e) => updateRow(i, { v: e.target.value })}
                placeholder="north_america"
              />
              <button
                type="button"
                onClick={() => removeRow(i)}
                className="text-subtle hover:text-red text-sm"
                aria-label="Remove entry"
              >
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addRow}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
          >
            + Add entry
          </button>
        </div>
      </Field>
    </div>
  );
}

export function MapExpressionEditor({ step, set }: { step: StepShape; set: Setter }) {
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Output field">
          <Input
            value={(step.output_field as string) ?? ""}
            onChange={(e) => set({ output_field: e.target.value })}
            placeholder="cohort_week"
          />
        </Field>
        <Field label="Mode">
          <select
            value={(step.mode as string) ?? "expression"}
            onChange={(e) => set({ mode: e.target.value as "expression" | "calculation" })}
            className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px] focus:outline-none focus:border-accent"
          >
            <option value="expression">expression</option>
            <option value="calculation">calculation</option>
          </select>
        </Field>
      </div>
      <Field label="Expression" hint="SQL expression">
        <Textarea
          value={(step.expr as string) ?? ""}
          onChange={(e) => set({ expr: e.target.value })}
          placeholder="date_trunc('week', created_at)"
        />
      </Field>
    </div>
  );
}

export function SortEditor({ step, set }: { step: StepShape; set: Setter }) {
  const { allFields } = useSchemas();
  const by = (step.by as string[]) ?? [];
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="Sort by" hint="fields evaluated in order">
        <FieldMultiSelect
          value={by}
          onChange={(v) => set({ by: v })}
          options={allFields}
          placeholder="add field to sort by…"
        />
      </Field>
      <Field label="Direction">
        <select
          value={String(step.ascending ?? true)}
          onChange={(e) => set({ ascending: e.target.value === "true" })}
          className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px] focus:outline-none focus:border-accent"
        >
          <option value="true">ascending</option>
          <option value="false">descending</option>
        </select>
      </Field>
    </div>
  );
}

const AGG_FUNCS = ["sum", "count", "avg", "min", "max", "count_distinct"];

interface AggSpec { field: string; func: string; alias: string }

export function AggregateEditor({ step, set }: { step: StepShape; set: Setter }) {
  const { allFields } = useSchemas();
  const group_by = (step.group_by as string[]) ?? [];
  const aggs = (step.aggregations as AggSpec[]) ?? [];

  const updateAgg = (i: number, patch: Partial<AggSpec>) => {
    const next = [...aggs];
    next[i] = { ...next[i], ...patch };
    set({ aggregations: next });
  };
  const addAgg = () =>
    set({ aggregations: [...aggs, { field: "", func: "sum", alias: "" }] });
  const removeAgg = (i: number) =>
    set({ aggregations: aggs.filter((_, j) => j !== i) });

  return (
    <div className="grid gap-3">
      <Field label="Group by" hint="fields to bucket rows by">
        <FieldMultiSelect
          value={group_by}
          onChange={(v) => set({ group_by: v })}
          options={allFields}
          placeholder="add group_by field…"
        />
      </Field>
      <div>
        <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle mb-1.5">
          Aggregations
        </div>
        <div className="grid gap-1.5">
          {aggs.map((a, i) => (
            <div key={i} className="grid grid-cols-[1fr_120px_1fr_28px] gap-2">
              <FieldPicker
                value={a.field}
                onChange={(v) => updateAgg(i, { field: v })}
                options={allFields}
                placeholder="amount"
              />
              <select
                value={a.func}
                onChange={(e) => updateAgg(i, { func: e.target.value })}
                className="bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px]"
              >
                {AGG_FUNCS.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
              <Input
                value={a.alias}
                onChange={(e) => updateAgg(i, { alias: e.target.value })}
                placeholder="gmv"
              />
              <button
                type="button"
                onClick={() => removeAgg(i)}
                className="text-subtle hover:text-red text-sm"
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={addAgg}
          className="mt-2 font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
        >
          + Add aggregation
        </button>
      </div>
    </div>
  );
}

export function JoinEditor({ step, set }: { step: StepShape; set: Setter }) {
  const { allFields } = useSchemas();
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-3 gap-3">
        <Field label="Left"><Input value={(step.left as string) ?? ""} onChange={(e) => set({ left: e.target.value })} /></Field>
        <Field label="Right"><Input value={(step.right as string) ?? ""} onChange={(e) => set({ right: e.target.value })} /></Field>
        <Field label="How">
          <select
            value={(step.how as string) ?? "inner"}
            onChange={(e) => set({ how: e.target.value })}
            className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px]"
          >
            {["inner", "left", "right", "outer"].map((h) => (
              <option key={h} value={h}>{h}</option>
            ))}
          </select>
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="On" hint="single field or comma-separated list">
          <FieldPicker
            value={Array.isArray(step.on) ? (step.on as string[]).join(", ") : (step.on as string) ?? ""}
            onChange={(v) => {
              const parts = v.split(",").map((s) => s.trim()).filter(Boolean);
              set({ on: parts.length > 1 ? parts : v });
            }}
            options={allFields}
            placeholder="user_id"
          />
        </Field>
        <Field label="Output id" hint="name of the resulting table in the registry">
          <Input value={(step.output_id as string) ?? ""} onChange={(e) => set({ output_id: e.target.value })} placeholder="joined" />
        </Field>
      </div>
    </div>
  );
}

const PIVOT_AGG = ["sum", "count", "avg", "min", "max"];

export function PivotEditor({ step, set }: { step: StepShape; set: Setter }) {
  const { allFields } = useSchemas();
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-3 gap-3">
        <Field label="Index"><FieldPicker value={(step.index as string) ?? ""} onChange={(v) => set({ index: v })} options={allFields} /></Field>
        <Field label="Columns"><FieldPicker value={(step.columns as string) ?? ""} onChange={(v) => set({ columns: v })} options={allFields} /></Field>
        <Field label="Values"><FieldPicker value={(step.values as string) ?? ""} onChange={(v) => set({ values: v })} options={allFields} /></Field>
      </div>
      <Field label="Aggregation">
        <select
          value={(step.agg as string) ?? "sum"}
          onChange={(e) => set({ agg: e.target.value })}
          className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px]"
        >
          {PIVOT_AGG.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
      </Field>
    </div>
  );
}

export function StepEditor({ step, set }: { step: StepShape; set: Setter }) {
  switch (step.op) {
    case "filter":    return <FilterEditor step={step} set={set} />;
    case "rename":    return <RenameEditor step={step} set={set} />;
    case "retype":    return <RetypeEditor step={step} set={set} />;
    case "map":       return step.mode === "lookup"
      ? <MapLookupEditor step={step} set={set} />
      : <MapExpressionEditor step={step} set={set} />;
    case "sort":      return <SortEditor step={step} set={set} />;
    case "aggregate": return <AggregateEditor step={step} set={set} />;
    case "join":      return <JoinEditor step={step} set={set} />;
    case "pivot":     return <PivotEditor step={step} set={set} />;
  }
}
