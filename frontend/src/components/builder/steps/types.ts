import useSWR from "swr";
import type { components } from "@/lib/api-types";
import type { PipelineTypeFilter } from "@/lib/pipeline-type";

type Schemas = components["schemas"];

/** A step as the backend accepts it — generated from the `Step` union
 *  (regenerate with `scripts/gen-api-types.sh`). */
export type Step = NonNullable<Schemas["PipelineBase"]["steps"]>[number];

export type StepOp = Step["op"];

/** One column a `structure` step pulls out of a document. */
export type DataModelField = Schemas["DataModelField"];

/** One column an `http_lookup` step reads out of each JSON response;
 *  `path` is JMESPath. */
export type HttpLookupField = Schemas["HttpLookupField"];

export type MapMode = Schemas["LookupMapStep"]["mode"] | Schemas["ExpressionMapStep"]["mode"];

/** Group-by entry for the aggregate step.
 *
 * A plain string is a field ref (backwards-compatible). A DatePartGroupBy
 * extracts a temporal component (year/month/etc) from a date/timestamp field.
 * Emitted column defaults to `<field>_<part>` unless `alias` is set.
 */
export type DatePartGroupBy = Schemas["DatePartGroupBy"];
export type DatePart = DatePartGroupBy["part"];

export type GroupByEntry = string | DatePartGroupBy;

/** Editor state: a step mid-edit, which need not be a valid `Step` yet
 *  (an empty filter, a join with no keys). Each editor reads the fields of
 *  its own op; save is where the backend's union is enforced. */
export interface StepShape {
  op: StepOp;
  mode?: MapMode;
  [k: string]: unknown;
}

export const STEP_OPS: {
  op: StepOp;
  label: string;
  mode?: MapMode;
}[] = [
  { op: "filter", label: "Filter" },
  { op: "rename", label: "Rename" },
  { op: "retype", label: "Retype" },
  { op: "map", label: "Map · lookup", mode: "lookup" },
  { op: "map", label: "Map · expression", mode: "expression" },
  { op: "case", label: "Case · if/else" },
  { op: "sort", label: "Sort" },
  { op: "aggregate", label: "Aggregate" },
  { op: "join", label: "Join" },
  { op: "pivot", label: "Pivot" },
  { op: "http_lookup", label: "HTTP lookup" },
  { op: "select", label: "Select / Drop fields" },
  { op: "extract", label: "Extract text" },
  { op: "structure", label: "Structure fields" },
  { op: "check", label: "Check" },
  { op: "profile", label: "Profile Columns" },
];

/** The `STEP_OPS` a pipeline type may hold — the backend's `ALLOWED_OPS`
 *  (`GET /api/allowed-ops`), the same table save validates against, so the
 *  menu never offers an op the save would refuse. Empty until it loads. */
export function useAllowedStepOps(pipelineType: PipelineTypeFilter) {
  const { data } = useSWR<Record<string, string[]>>("/api/allowed-ops");
  const allowed = data?.[pipelineType] ?? [];
  return STEP_OPS.filter((o) => allowed.includes(o.op));
}

export function emptyStep(op: StepOp, mode?: MapMode): StepShape {
  switch (op) {
    case "filter":
      return { op, expr: "" };
    case "rename":
      return { op, mappings: {} };
    case "retype":
      return { op, field: "", to_type: "string" };
    case "map":
      return mode === "lookup"
        ? { op, mode, field: "", lookup_id: "", output_field: null }
        : { op, mode: mode ?? "expression", output_field: "", expr: "" };
    // One starter branch: the backend requires min_length=1, and a step you
    // can't save is a worse first impression than a placeholder.
    case "case":
      return {
        op,
        output_field: "",
        branches: [{ when: [{ field: "", op: "=", value: "", join: "AND" }], then: null }],
        otherwise: null,
      };
    case "sort":
      return { op, by: [], ascending: true };
    case "aggregate":
      return { op, group_by: [], aggregations: [] };
    case "join":
      return { op, left: "", right: "", on: "", how: "inner", output_id: "" };
    case "pivot":
      return { op, index: "", columns: "", values: "", agg: "sum" };
    case "select":
      return { op, fields: [] };
    case "check":
      return { op, expr: "", label: "", severity: "fail" };
    case "profile":
      return { op, columns: [] };
    case "extract":
      return {
        op,
        source_field: "path",
        provider: "pdfplumber",
        granularity: "page",
        output_field: "content",
        params: {},
      };
    // One starter field: an empty data model is rejected by the backend, and
    // a step you can't save is a worse first impression than a placeholder.
    case "structure":
      return {
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
    // Same starter-field reasoning as `structure`: no fields is rejected.
    case "http_lookup":
      return {
        op,
        url: "https://",
        fields: [{ name: "", path: "", type: "string" }] satisfies HttpLookupField[],
        max_rows: 500,
        on_error: "null",
      };
  }
}

export function labelFor(step: StepShape): string {
  if (step.op === "map") return `map · ${step.mode ?? "?"}`;
  return step.op;
}
