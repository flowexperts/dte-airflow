"use client";

import { useEffect, useState } from "react";
import {
  Field,
  FieldPicker,
  FieldMultiSelect,
  Input,
  Segmented,
  Textarea,
} from "@/components/ui";
import { useSchemas } from "../schema-context";
import { toDisplay } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { StepShape } from "./types";
import { LookupTablePicker } from "../LookupTablePicker";

type Setter = (patch: Partial<StepShape>) => void;

/* --------------- Filter — Basic + Advanced tabs --------------- */

type FilterOp =
  | "="
  | "!="
  | ">"
  | "<"
  | ">="
  | "<="
  | "LIKE"
  | "IN"
  | "IS NULL"
  | "IS NOT NULL"
  | "BETWEEN";

interface FilterRule {
  field: string;
  op: FilterOp;
  value: string;
  join: "AND" | "OR";
}

const FILTER_OPS: FilterOp[] = [
  "=", "!=", ">", "<", ">=", "<=", "LIKE", "IN", "IS NULL", "IS NOT NULL", "BETWEEN",
];

const OPS_WITHOUT_VALUE = new Set<FilterOp>(["IS NULL", "IS NOT NULL"]);

/** DuckDB identifier quote — wraps in "" and escapes internal " as "".
 *  Dots navigate STRUCT members, so each dot-separated segment is quoted
 *  individually: `order.amount` → `"order"."amount"`.  A single quoted
 *  `"order.amount"` would ask DuckDB for a top-level column literally
 *  named `order.amount`, which is not what struct paths mean. */
function quoteIdent(name: string): string {
  return name
    .split(".")
    .map((seg) => `"${seg.replace(/"/g, '""')}"`)
    .join(".");
}

/** DuckDB string literal quote — wraps in '' and escapes internal ' as ''. */
function quoteString(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

/**
 * Turn a value into a safe SQL literal.
 * Bare numbers (int or float) pass through as-is; everything else is quoted as string.
 * Never concatenates raw user input into the SQL string without going through here.
 */
function safeLiteral(v: string): string {
  const trimmed = v.trim();
  if (trimmed === "") return "''";
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return trimmed;
  if (/^(true|false)$/i.test(trimmed)) return trimmed.toUpperCase();
  return quoteString(trimmed);
}

function ruleToSql(r: FilterRule): string {
  if (!r.field) return "";
  const f = quoteIdent(r.field);
  switch (r.op) {
    case "IS NULL":
    case "IS NOT NULL":
      return `${f} ${r.op}`;
    case "IN": {
      const parts = r.value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map(safeLiteral);
      if (parts.length === 0) return "";
      return `${f} IN (${parts.join(", ")})`;
    }
    case "BETWEEN": {
      const parts = r.value.split(",").map((s) => s.trim()).filter(Boolean);
      if (parts.length !== 2) return "";
      return `${f} BETWEEN ${safeLiteral(parts[0])} AND ${safeLiteral(parts[1])}`;
    }
    case "LIKE":
      return `${f} LIKE ${safeLiteral(r.value)}`;
    default:
      return `${f} ${r.op} ${safeLiteral(r.value)}`;
  }
}

function rulesToSql(rules: FilterRule[]): string {
  const parts: string[] = [];
  rules.forEach((r, i) => {
    const sql = ruleToSql(r);
    if (!sql) return;
    if (parts.length === 0) parts.push(sql);
    else parts.push(`${r.join} ${sql}`);
  });
  return parts.join(" ");
}

export function FilterEditor({ step, set }: { step: StepShape; set: Setter }) {
  const { allFields } = useSchemas();

  // Mode is local UI state — not persisted on the step. On first mount, if
  // there's an existing expr, default to Advanced (we don't try to parse
  // arbitrary SQL back into structured rules).
  const initialMode: "basic" | "advanced" = step.expr ? "advanced" : "basic";
  const [mode, setMode] = useState<"basic" | "advanced">(initialMode);
  const [rules, setRules] = useState<FilterRule[]>([]);

  const commitRules = (next: FilterRule[]) => {
    setRules(next);
    set({ expr: rulesToSql(next) });
  };

  const addRule = () =>
    commitRules([
      ...rules,
      { field: "", op: "=", value: "", join: "AND" },
    ]);
  const updateRule = (i: number, patch: Partial<FilterRule>) =>
    commitRules(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const removeRule = (i: number) =>
    commitRules(rules.filter((_, j) => j !== i));

  const previewExpr = mode === "basic" ? rulesToSql(rules) : ((step.expr as string) ?? "");

  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <div className="inline-flex border border-border rounded-[var(--radius)] bg-surface p-0.5">
          {(["basic", "advanced"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                if (m === "basic" && mode === "advanced") {
                  // Switching from Advanced back to Basic: clear rules so the
                  // user can rebuild. We do not attempt to parse arbitrary SQL.
                  commitRules([]);
                }
                setMode(m);
              }}
              className={cn(
                "px-3 py-1 text-[12.5px] font-medium rounded-[3px] transition-colors capitalize",
                m === mode
                  ? "bg-[color:var(--accent-tint)] text-accent"
                  : "text-muted hover:text-text",
              )}
            >
              {m}
            </button>
          ))}
        </div>
        <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">
          {mode === "basic" ? "structured · safe" : "raw sql"}
        </span>
      </div>

      {mode === "basic" ? (
        <div className="space-y-1.5">
          {rules.length === 0 && (
            <div className="font-mono text-[11.5px] text-subtle">
              No conditions. Add one below.
            </div>
          )}
          {rules.map((r, i) => {
            const noValue = OPS_WITHOUT_VALUE.has(r.op);
            return (
              <div
                key={i}
                className="grid grid-cols-[60px_1.4fr_120px_1.4fr_28px] gap-2 items-center"
              >
                {i === 0 ? (
                  <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle text-center">
                    where
                  </span>
                ) : (
                  <select
                    value={r.join}
                    onChange={(e) => updateRule(i, { join: e.target.value as "AND" | "OR" })}
                    className="w-full bg-bg border border-border rounded px-2 py-1.5 text-[12.5px] focus:outline-none focus:border-accent"
                  >
                    <option value="AND">AND</option>
                    <option value="OR">OR</option>
                  </select>
                )}
                <FieldPicker
                  value={r.field}
                  onChange={(v) => updateRule(i, { field: v })}
                  options={allFields}
                  placeholder="field"
                  variant="tree"
                />
                <select
                  value={r.op}
                  onChange={(e) => updateRule(i, { op: e.target.value as FilterOp })}
                  className="w-full bg-bg border border-border rounded px-2 py-1.5 text-[12.5px] font-mono focus:outline-none focus:border-accent"
                >
                  {FILTER_OPS.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
                <Input
                  value={r.value}
                  onChange={(e) => updateRule(i, { value: e.target.value })}
                  placeholder={
                    r.op === "IN"
                      ? "a, b, c"
                      : r.op === "BETWEEN"
                        ? "min, max"
                        : "value"
                  }
                  disabled={noValue}
                />
                <button
                  type="button"
                  onClick={() => removeRule(i)}
                  className="text-subtle hover:text-red text-sm"
                  aria-label="Remove condition"
                >
                  ×
                </button>
              </div>
            );
          })}
          <button
            type="button"
            onClick={addRule}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
          >
            + Add condition
          </button>
          {previewExpr && (
            <div className="mt-2">
              <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle mb-1">
                Generated SQL
              </div>
              <code className="block font-mono text-[12px] text-muted bg-code-bg border border-border rounded px-2.5 py-1.5 whitespace-pre-wrap break-words">
                {previewExpr}
              </code>
            </div>
          )}
        </div>
      ) : (
        <Field
          label="Expression"
          hint="raw DuckDB WHERE clause. You are responsible for quoting — for safe, structured input use Basic."
        >
          <Textarea
            value={(step.expr as string) ?? ""}
            onChange={(e) => set({ expr: e.target.value })}
            placeholder="amount > 0 AND status = 'completed'"
          />
        </Field>
      )}
    </div>
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
              variant="tree"
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
          variant="tree"
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
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Field">
          <FieldPicker
            value={(step.field as string) ?? ""}
            onChange={(v) => set({ field: v })}
            options={allFields}
            variant="tree"
          />
        </Field>
        <Field
          label="Output field (optional)"
          hint="leave blank to overwrite the input column"
        >
          <Input
            value={(step.output_field as string) ?? ""}
            onChange={(e) => set({ output_field: e.target.value || null })}
            placeholder="country_name"
          />
        </Field>
      </div>
      <LookupTablePicker
        value={(step.lookup_id as string) ?? ""}
        onChange={(v) => set({ lookup_id: v })}
      />
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
          variant="tree"
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
          variant="tree"
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
                variant="tree"
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
            variant="tree"
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
        <Field label="Index"><FieldPicker value={(step.index as string) ?? ""} onChange={(v) => set({ index: v })} options={allFields} variant="tree" /></Field>
        <Field label="Columns"><FieldPicker value={(step.columns as string) ?? ""} onChange={(v) => set({ columns: v })} options={allFields} variant="tree" /></Field>
        <Field label="Values"><FieldPicker value={(step.values as string) ?? ""} onChange={(v) => set({ values: v })} options={allFields} variant="tree" /></Field>
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

/* --------------- Select — pick/drop fields with optional aliases --------------- */

interface SelectField { field: string; alias?: string | null }

export function SelectEditor({ step, set }: { step: StepShape; set: Setter }) {
  const { allFields } = useSchemas();
  const fields = (step.fields as SelectField[]) ?? [];
  const dropped = (step.drop as string[]) ?? [];
  const knownNames = allFields.map((f) => f.name);

  // Mode is UI-local so the user can be in drop mode with zero entries
  // (a valid transitional state). Initial mode reflects what's persisted:
  // `drop` non-empty means we opened an existing drop step. Backend
  // enforces mutual exclusion; we mirror that on save.
  const [mode, setMode] = useState<"keep" | "drop">(
    dropped.length > 0 ? "drop" : "keep",
  );

  const keepNames = fields.map((f) => f.field);
  const setKeep = (names: string[]) => {
    const prev = new Map(fields.map((f) => [f.field, f.alias ?? null]));
    set({
      fields: names.map((n) => ({ field: n, alias: prev.get(n) ?? null })),
    });
  };
  const setDropped = (names: string[]) => {
    set({ drop: names });
  };
  const setAlias = (field: string, alias: string) => {
    set({
      fields: fields.map((f) =>
        f.field === field ? { ...f, alias: alias || null } : f,
      ),
    });
  };

  const changeMode = (m: "keep" | "drop") => {
    if (m === mode) return;
    setMode(m);
    // Clear the other list so the step only carries the active-mode data.
    if (m === "keep") set({ drop: [] });
    else set({ fields: [] });
  };

  // Warn only when the current mode would emit an empty step, which the
  // backend rejects (SelectStep requires one of `fields` or `drop`).
  const warn = mode === "keep" ? fields.length === 0 : dropped.length === 0;

  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">
          {mode === "keep" ? "keep only listed" : "drop listed, keep the rest"}
        </span>
        <Segmented<"keep" | "drop">
          value={mode}
          onChange={changeMode}
          options={[
            { value: "keep", label: "Select fields" },
            { value: "drop", label: "Drop fields" },
          ]}
        />
      </div>

      {warn && (
        <div className="font-mono text-[11.5px] text-gold px-2.5 py-1.5 border border-gold rounded bg-[color:color-mix(in_srgb,var(--gold)_10%,transparent)]">
          {mode === "keep"
            ? "Pick at least one field, otherwise the pipeline projection is empty and runs will fail."
            : "Add at least one field to drop — the backend rejects an empty select step."}
        </div>
      )}

      {mode === "keep" ? (
        <div className="space-y-3">
          <FieldMultiSelect
            value={keepNames}
            onChange={setKeep}
            options={allFields}
            placeholder="add field to keep…"
            variant="tree"
          />
          {fields.length > 0 && (
            <div className="space-y-1.5">
              <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
                Aliases (optional)
              </div>
              {fields.map((f) => (
                <div
                  key={f.field}
                  className="grid grid-cols-[1fr_16px_1fr] gap-2 items-center"
                >
                  <span className="font-mono text-[12.5px] text-text px-2.5 py-1.5 border border-border rounded bg-code-bg">
                    {toDisplay(f.field)}
                  </span>
                  <span className="text-subtle text-center">→</span>
                  <Input
                    value={f.alias ?? ""}
                    onChange={(e) => setAlias(f.field, e.target.value)}
                    placeholder={toDisplay(f.field)}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {knownNames.length === 0 ? (
            <p className="font-mono text-[11.5px] text-subtle">
              Infer the source schema first so you can pick which fields to drop.
            </p>
          ) : (
            <>
              <FieldMultiSelect
                value={dropped}
                onChange={setDropped}
                options={allFields}
                placeholder="add field to drop…"
                variant="tree"
              />
              <p className="font-mono text-[11px] text-subtle">
                Drop is applied at run time — fields added to the source later pass through automatically.
              </p>
            </>
          )}
        </div>
      )}
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
    case "select":    return <SelectEditor step={step} set={set} />;
  }
}
