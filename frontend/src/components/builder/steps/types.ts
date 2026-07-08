export type StepOp =
  | "filter"
  | "rename"
  | "retype"
  | "map"
  | "sort"
  | "aggregate"
  | "join"
  | "pivot";

export type MapMode = "lookup" | "expression" | "calculation";

export interface StepShape {
  op: StepOp;
  mode?: MapMode;
  [k: string]: unknown;
}

export const STEP_OPS: { op: StepOp; label: string; mode?: MapMode }[] = [
  { op: "filter",    label: "Filter" },
  { op: "rename",    label: "Rename" },
  { op: "retype",    label: "Retype" },
  { op: "map",       label: "Map · lookup",     mode: "lookup" },
  { op: "map",       label: "Map · expression", mode: "expression" },
  { op: "sort",      label: "Sort" },
  { op: "aggregate", label: "Aggregate" },
  { op: "join",      label: "Join" },
  { op: "pivot",     label: "Pivot" },
];

export function emptyStep(op: StepOp, mode?: MapMode): StepShape {
  switch (op) {
    case "filter":    return { op, expr: "" };
    case "rename":    return { op, mappings: {} };
    case "retype":    return { op, field: "", to_type: "string" };
    case "map":       return mode === "lookup"
                        ? { op, mode, field: "", table: {}, default: null }
                        : { op, mode: mode ?? "expression", output_field: "", expr: "" };
    case "sort":      return { op, by: [], ascending: true };
    case "aggregate": return { op, group_by: [], aggregations: [] };
    case "join":      return { op, left: "", right: "", on: "", how: "inner", output_id: "" };
    case "pivot":     return { op, index: "", columns: "", values: "", agg: "sum" };
  }
}

export function labelFor(step: StepShape): string {
  if (step.op === "map") return `map · ${step.mode ?? "?"}`;
  return step.op;
}
