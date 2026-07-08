"use client";

import { Field, Input, Textarea } from "@/components/ui";
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

export function RenameEditor({ step, set }: { step: StepShape; set: Setter }) {
  const mappings = (step.mappings as Record<string, string>) ?? {};
  const asText = Object.entries(mappings)
    .map(([k, v]) => `${k} → ${v}`)
    .join("\n");

  const parse = (t: string): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const line of t.split("\n")) {
      const [k, v] = line.split(/→|->/).map((s) => s.trim());
      if (k && v) out[k] = v;
    }
    return out;
  };

  return (
    <Field label="Mappings" hint="one per line: old_name → new_name">
      <Textarea
        value={asText}
        onChange={(e) => set({ mappings: parse(e.target.value) })}
        placeholder={"customer_id → user_id\norder_ts → created_at"}
        rows={4}
      />
    </Field>
  );
}

const RETYPE_OPTIONS = ["string", "int", "float", "boolean", "date", "timestamp"];

export function RetypeEditor({ step, set }: { step: StepShape; set: Setter }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="Field">
        <Input
          value={(step.field as string) ?? ""}
          onChange={(e) => set({ field: e.target.value })}
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
  const table = (step.table as Record<string, string>) ?? {};
  const asText = Object.entries(table).map(([k, v]) => `${k} = ${v}`).join("\n");
  const parse = (t: string): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const line of t.split("\n")) {
      const [k, v] = line.split("=").map((s) => s.trim());
      if (k && v) out[k] = v;
    }
    return out;
  };
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Field">
          <Input
            value={(step.field as string) ?? ""}
            onChange={(e) => set({ field: e.target.value })}
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
      <Field label="Lookup table" hint="one per line: key = value">
        <Textarea
          value={asText}
          onChange={(e) => set({ table: parse(e.target.value) })}
          placeholder={"US = north_america\nCA = north_america\nGB = europe"}
          rows={4}
        />
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
  const by = (step.by as string[]) ?? [];
  const asText = by.join(", ");
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="Sort by" hint="comma-separated field names">
        <Input
          value={asText}
          onChange={(e) =>
            set({ by: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })
          }
          placeholder="gmv, cohort_week"
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
  const group_by = ((step.group_by as string[]) ?? []).join(", ");
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
      <Field label="Group by" hint="comma-separated field names">
        <Input
          value={group_by}
          onChange={(e) =>
            set({
              group_by: e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
          placeholder="region, cohort_week"
        />
      </Field>
      <div>
        <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle mb-1.5">
          Aggregations
        </div>
        <div className="grid gap-1.5">
          {aggs.map((a, i) => (
            <div key={i} className="grid grid-cols-[1fr_120px_1fr_28px] gap-2">
              <Input
                value={a.field}
                onChange={(e) => updateAgg(i, { field: e.target.value })}
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
          <Input
            value={Array.isArray(step.on) ? (step.on as string[]).join(", ") : (step.on as string) ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              const parts = v.split(",").map((s) => s.trim()).filter(Boolean);
              set({ on: parts.length > 1 ? parts : v });
            }}
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
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-3 gap-3">
        <Field label="Index"><Input value={(step.index as string) ?? ""} onChange={(e) => set({ index: e.target.value })} /></Field>
        <Field label="Columns"><Input value={(step.columns as string) ?? ""} onChange={(e) => set({ columns: e.target.value })} /></Field>
        <Field label="Values"><Input value={(step.values as string) ?? ""} onChange={(e) => set({ values: e.target.value })} /></Field>
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
