export type StepOp =
  | "filter"
  | "rename"
  | "retype"
  | "map"
  | "case"
  | "sort"
  | "aggregate"
  | "join"
  | "pivot"
  | "select"
  | "check"
  | "profile"
  | "extract"
  | "structure";

/** One column a `structure` step pulls out of a document. Mirrors the
 *  backend's `DataModelField`. */
export interface DataModelField {
  name: string;
  type: "string" | "int" | "float" | "boolean" | "date" | "timestamp";
  description: string;
  required: boolean;
  /** Only read by the deterministic `regex` provider. */
  pattern?: string | null;
}

export type MapMode = "lookup" | "expression" | "calculation";

/** Group-by entry for the aggregate step.
 *
 * A plain string is a field ref (backwards-compatible). A DatePartGroupBy
 * extracts a temporal component (year/month/etc) from a date/timestamp field.
 * Emitted column defaults to `<field>_<part>` unless `alias` is set.
 */
export type DatePart =
  | "year"
  | "quarter"
  | "month"
  | "week"
  | "day"
  | "date"
  | "dow"
  | "hour";

export interface DatePartGroupBy {
  field: string;
  part: DatePart;
  alias?: string;
}

export type GroupByEntry = string | DatePartGroupBy;

export interface StepShape {
  op: StepOp;
  mode?: MapMode;
  [k: string]: unknown;
}

export const STEP_OPS: { op: StepOp; label: string; mode?: MapMode; category: "transform" | "quality" | "extract" }[] = [
  { op: "filter",    label: "Filter",              category: "transform" },
  { op: "rename",    label: "Rename",              category: "transform" },
  { op: "retype",    label: "Retype",              category: "transform" },
  { op: "map",       label: "Map · lookup",        mode: "lookup",     category: "transform" },
  { op: "map",       label: "Map · expression",    mode: "expression", category: "transform" },
  { op: "case",      label: "Case · if/else",       category: "transform" },
  { op: "sort",      label: "Sort",                category: "transform" },
  { op: "aggregate", label: "Aggregate",           category: "transform" },
  { op: "join",      label: "Join",                category: "transform" },
  { op: "pivot",     label: "Pivot",               category: "transform" },
  { op: "select",    label: "Select / Drop fields", category: "transform" },
  { op: "extract",   label: "Extract text",        category: "extract" },
  { op: "structure", label: "Structure fields",    category: "extract" },
  { op: "check",                label: "Check",                  category: "quality" },
  { op: "profile",              label: "Profile Columns",        category: "quality" },
];

export function emptyStep(op: StepOp, mode?: MapMode): StepShape {
  switch (op) {
    case "filter":    return { op, expr: "" };
    case "rename":    return { op, mappings: {} };
    case "retype":    return { op, field: "", to_type: "string" };
    case "map":       return mode === "lookup"
                        ? { op, mode, field: "", lookup_id: "", output_field: null }
                        : { op, mode: mode ?? "expression", output_field: "", expr: "" };
    // One starter branch: the backend requires min_length=1, and a step you
    // can't save is a worse first impression than a placeholder.
    case "case":      return { op, output_field: "", branches: [{ when: "", then: "" }], otherwise: null };
    case "sort":      return { op, by: [], ascending: true };
    case "aggregate": return { op, group_by: [], aggregations: [] };
    case "join":      return { op, left: "", right: "", on: "", how: "inner", output_id: "" };
    case "pivot":     return { op, index: "", columns: "", values: "", agg: "sum" };
    case "select":              return { op, fields: [] };
    case "check":               return { op, expr: "", label: "", severity: "fail" };
    case "profile":             return { op, columns: [] };
    case "extract":   return {
      op,
      source_field: "path",
      provider: "pdfplumber",
      granularity: "page",
      output_field: "content",
      params: {},
    };
    // One starter field: an empty data model is rejected by the backend, and
    // a step you can't save is a worse first impression than a placeholder.
    case "structure": return {
      op,
      input_field: "content",
      provider: "claude",
      model: {
        fields: [
          { name: "", type: "string", description: "", required: false },
        ] satisfies DataModelField[],
        instructions: "",
      },
      params: {},
      on_error: "null",
    };
  }
}

export function labelFor(step: StepShape): string {
  if (step.op === "map") return `map · ${step.mode ?? "?"}`;
  return step.op;
}
