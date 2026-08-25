import type { ReactNode } from "react";
import { ExprCode, ExprToken, KV, KVItem } from "@/components/ui";
import type { DatePartGroupBy, GroupByEntry, StepShape } from "./types";

/* Read-only rendering of a step. The builder has an editor per op
 * (`editors.tsx`); this is the other half — what a step looks like when you're
 * reading rather than changing it. Detail pages and collapsed builder rows
 * share it so a step never reads differently in two places. */

interface AggSpec {
  field?: string;
  func?: string;
  alias?: string;
}

const str = (v: unknown): string | null =>
  typeof v === "string" && v.trim() !== "" ? v : null;

const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

const groupByLabel = (g: GroupByEntry): string => {
  if (typeof g === "string") return g;
  const d = g as DatePartGroupBy;
  return d.alias || `${d.field}_${d.part}`;
};

const aggLabel = (a: AggSpec): string =>
  a.alias || `${a.func ?? "?"}(${a.field ?? "?"})`;

/** Count noun that stays readable at 0 and 1. */
const n = (count: number, singular: string, plural = `${singular}s`) =>
  `${count} ${count === 1 ? singular : plural}`;

/**
 * One-line headline for a step — what goes next to the op badge.
 * Falls back to the op name so a half-built step still renders something.
 */
export function stepTitle(step: StepShape): string {
  switch (step.op) {
    case "filter":
      return str(step.expr) ?? "no condition yet";
    case "rename": {
      const m = (step.mappings as Record<string, string>) ?? {};
      const keys = Object.keys(m);
      const only = keys[0];
      if (only === undefined) return "no mappings yet";
      if (keys.length === 1) return `${only} → ${m[only]}`;
      return n(keys.length, "field") + " renamed";
    }
    case "retype":
      return `${str(step.field) ?? "?"} → ${str(step.to_type) ?? "?"}`;
    case "map":
      return step.mode === "lookup"
        ? `${str(step.field) ?? "?"} via ${str(step.lookup_id) ?? "no table"}`
        : (str(step.output_field) ?? "unnamed field");
    case "sort": {
      const by = list(step.by).filter((x): x is string => typeof x === "string");
      const dir = step.ascending === false ? "desc" : "asc";
      return by.length === 0 ? "no sort fields" : `${by.join(", ")} ${dir}`;
    }
    case "aggregate": {
      const groups = list(step.group_by) as GroupByEntry[];
      const aggs = list(step.aggregations) as AggSpec[];
      if (groups.length === 0 && aggs.length === 0) return "not configured";
      const by = groups.map(groupByLabel).join(", ");
      return by ? `by ${by}` : n(aggs.length, "aggregation");
    }
    case "case": {
      const branches = list(step.branches);
      const out = str(step.output_field);
      if (!out) return "unnamed field";
      return `${out} · ${n(branches.length, "branch")}`;
    }
    case "date_diff": {
      const out = str(step.output_field);
      return out ? `${out} · ${str(step.unit) ?? "year"}s` : "not configured";
    }
    case "join":
      return `${str(step.left) ?? "?"} ${str(step.how) ?? "inner"} ${str(step.right) ?? "?"}`;
    case "pivot":
      return `${str(step.columns) ?? "?"} → columns`;
    case "select": {
      const fields = list(step.fields);
      return fields.length === 0 ? "no fields selected" : n(fields.length, "field") + " kept";
    }
    case "check":
      return str(step.label) ?? str(step.expr) ?? "unnamed check";
    case "profile": {
      const cols = list(step.columns);
      return cols.length === 0 ? "all columns" : n(cols.length, "column");
    }
    case "extract":
      return `${str(step.provider) ?? "?"} · per ${str(step.granularity) ?? "page"}`;
    case "structure": {
      const fields = list(
        (step.model as { fields?: unknown[] } | undefined)?.fields,
      );
      if (fields.length === 0) return "no fields declared";
      return `${n(fields.length, "field")} via ${str(step.provider) ?? "?"}`;
    }
    default:
      return String(step.op);
  }
}

/**
 * The detail line under the headline. Returns null when the headline already
 * says everything — an empty row is better than a row repeating itself.
 */
export function StepSummary({ step }: { step: StepShape }): ReactNode {
  switch (step.op) {
    case "filter":
    case "check": {
      const expr = str(step.expr);
      if (!expr) return null;
      return (
        <div className="flex items-center gap-2 flex-wrap">
          <ExprCode>{expr}</ExprCode>
          {step.op === "check" && step.severity === "warn" && (
            <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-gold">
              warn only
            </span>
          )}
        </div>
      );
    }

    case "rename": {
      const m = (step.mappings as Record<string, string>) ?? {};
      const entries = Object.entries(m);
      if (entries.length === 0) return null;
      return (
        <KV>
          {entries.map(([from, to]) => (
            <KVItem
              key={from}
              label={from}
              value={
                <>
                  <ExprToken as="op">→</ExprToken>{" "}
                  <ExprToken as="field">{to}</ExprToken>
                </>
              }
            />
          ))}
        </KV>
      );
    }

    case "retype":
      return null;

    case "map": {
      if (step.mode === "lookup") {
        const out = str(step.output_field);
        return (
          <KV>
            <KVItem label="table" value={str(step.lookup_id) ?? "—"} />
            {out && <KVItem label="writes" value={out} />}
          </KV>
        );
      }
      const expr = str(step.expr);
      return expr ? <ExprCode>{expr}</ExprCode> : null;
    }

    case "sort":
      return null;

    case "aggregate": {
      const aggs = (list(step.aggregations) as AggSpec[]).filter(
        (a) => a.field || a.alias,
      );
      if (aggs.length === 0) return null;
      return (
        <KV>
          {aggs.map((a, i) => (
            <KVItem key={i} label={aggLabel(a)} />
          ))}
        </KV>
      );
    }

    case "join": {
      const on = str(step.on);
      return (
        <KV>
          {on && <KVItem label="on" value={on} />}
          {str(step.output_id) && <KVItem label="as" value={str(step.output_id)} />}
        </KV>
      );
    }

    case "case": {
      type Cond = { field?: string; op?: string; value?: string; join?: string };
      const branches = list(step.branches) as { when?: Cond[]; then?: unknown }[];
      if (branches.length === 0) return null;
      const condText = (c: Cond) =>
        [c.field ?? "?", c.op ?? "=", c.value].filter(Boolean).join(" ");
      return (
        <KV>
          {branches.map((b, i) => (
            <KVItem
              key={i}
              label={i === 0 ? "if" : "else if"}
              value={`${(b.when ?? []).map(condText).join(" · ") || "?"} → ${
                b.then === null || b.then === undefined ? "null" : String(b.then)
              }`}
            />
          ))}
          {step.otherwise !== null && step.otherwise !== undefined && (
            <KVItem label="else" value={String(step.otherwise)} />
          )}
        </KV>
      );
    }

    case "date_diff":
      return (
        <KV>
          <KVItem label="up to" value={str(step.to) ?? "—"} />
          <KVItem label="unit" value={str(step.unit) ?? "year"} />
        </KV>
      );

    case "pivot":
      return (
        <KV>
          <KVItem label="index" value={str(step.index) ?? "—"} />
          <KVItem label="values" value={str(step.values) ?? "—"} />
          <KVItem label="agg" value={str(step.agg) ?? "—"} />
        </KV>
      );

    case "select": {
      const fields = list(step.fields);
      if (fields.length === 0) return null;
      // Field entries are either a plain name or {field, alias}.
      const names = fields.map((f) =>
        typeof f === "string"
          ? f
          : ((f as { alias?: string; field?: string }).alias ??
            (f as { field?: string }).field ??
            "?"),
      );
      const shown = names.slice(0, 8);
      return (
        <KV>
          {shown.map((f, i) => (
            <KVItem key={i} label={f} />
          ))}
          {names.length > shown.length && (
            <KVItem label={`+${names.length - shown.length} more`} />
          )}
        </KV>
      );
    }

    case "profile": {
      const cols = list(step.columns).filter(
        (c): c is string => typeof c === "string",
      );
      if (cols.length === 0) return null;
      return (
        <KV>
          {cols.map((c) => (
            <KVItem key={c} label={c} />
          ))}
        </KV>
      );
    }

    case "extract":
      return (
        <KV>
          <KVItem label="reads" value={str(step.source_field) ?? "path"} />
          <KVItem label="writes" value={str(step.output_field) ?? "content"} />
        </KV>
      );

    case "structure": {
      const model = step.model as
        | { fields?: { name?: string; type?: string }[] }
        | undefined;
      const fields = (list(model?.fields) as { name?: string; type?: string }[])
        .filter((f) => f.name);
      if (fields.length === 0) return null;
      const shown = fields.slice(0, 8);
      return (
        <KV>
          {shown.map((f, i) => (
            <KVItem key={i} label={f.name ?? "?"} value={f.type ?? "string"} />
          ))}
          {fields.length > shown.length && (
            <KVItem label={`+${fields.length - shown.length} more`} />
          )}
        </KV>
      );
    }

    default:
      return null;
  }
}
