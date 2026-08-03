export type StepOp =
  | "filter"
  | "rename"
  | "retype"
  | "map"
  | "sort"
  | "aggregate"
  | "join"
  | "pivot"
  | "select"
  | "check_not_null"
  | "check_unique"
  | "check_range"
  | "check_regex"
  | "check_accepted_values"
  | "check_row_count"
  | "check_custom_sql"
  | "profile";

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

export const STEP_OPS: { op: StepOp; label: string; mode?: MapMode; category: "transform" | "quality" }[] = [
  { op: "filter",    label: "Filter",              category: "transform" },
  { op: "rename",    label: "Rename",              category: "transform" },
  { op: "retype",    label: "Retype",              category: "transform" },
  { op: "map",       label: "Map · lookup",        mode: "lookup",     category: "transform" },
  { op: "map",       label: "Map · expression",    mode: "expression", category: "transform" },
  { op: "sort",      label: "Sort",                category: "transform" },
  { op: "aggregate", label: "Aggregate",           category: "transform" },
  { op: "join",      label: "Join",                category: "transform" },
  { op: "pivot",     label: "Pivot",               category: "transform" },
  { op: "select",    label: "Select / Drop fields", category: "transform" },
  { op: "check_not_null",       label: "Check: Not Null",        category: "quality" },
  { op: "check_unique",         label: "Check: Unique",          category: "quality" },
  { op: "check_range",          label: "Check: Range",           category: "quality" },
  { op: "check_regex",          label: "Check: Regex",           category: "quality" },
  { op: "check_accepted_values", label: "Check: Accepted Values", category: "quality" },
  { op: "check_row_count",      label: "Check: Row Count",       category: "quality" },
  { op: "check_custom_sql",     label: "Check: Custom SQL",      category: "quality" },
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
    case "sort":      return { op, by: [], ascending: true };
    case "aggregate": return { op, group_by: [], aggregations: [] };
    case "join":      return { op, left: "", right: "", on: "", how: "inner", output_id: "" };
    case "pivot":     return { op, index: "", columns: "", values: "", agg: "sum" };
    case "select":              return { op, fields: [] };
    case "check_not_null":      return { op, column: "", severity: "fail" };
    case "check_unique":        return { op, column: "", severity: "fail" };
    case "check_range":         return { op, column: "", min: null, max: null, severity: "fail" };
    case "check_regex":         return { op, column: "", pattern: "", severity: "fail" };
    case "check_accepted_values": return { op, column: "", values: [], severity: "fail" };
    case "check_row_count":     return { op, min: null, max: null, severity: "fail" };
    case "check_custom_sql":    return { op, sql: "", label: "", severity: "fail" };
    case "profile":             return { op, columns: [] };
  }
}

export function labelFor(step: StepShape): string {
  if (step.op === "map") return `map · ${step.mode ?? "?"}`;
  return step.op;
}
