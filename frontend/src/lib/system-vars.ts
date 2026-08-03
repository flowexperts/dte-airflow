import type { ParamType } from "@/lib/api";

/**
 * System variables resolved at trigger time by the backend interpolator.
 * Keep in sync with `SYSTEM_VAR_NAMES` in `backend/dte/compiler/interpolate.py`.
 */
export const SYSTEM_VARS = [
  "now",
  "today",
  "yesterday",
  "start_of_week",
  "start_of_month",
] as const;

export type SystemVar = (typeof SYSTEM_VARS)[number];

/** ISO shape each system var produces. */
export const SYSTEM_VAR_KIND: Record<SystemVar, "date" | "timestamp"> = {
  now: "timestamp",
  today: "date",
  yesterday: "date",
  start_of_week: "date",
  start_of_month: "date",
};

/**
 * System vars that make sense to bind to a param of a given declared type.
 * FE-only filter for the ParamsModal dropdown — the backend accepts any
 * system var against any type and returns 422 if the ISO string doesn't
 * coerce.
 */
export function compatibleFor(paramType: ParamType): readonly SystemVar[] {
  switch (paramType) {
    case "timestamp":
    case "string":
      return SYSTEM_VARS;
    case "date":
      return SYSTEM_VARS.filter((v) => SYSTEM_VAR_KIND[v] === "date");
    default:
      return [];
  }
}

const DYNAMIC_SENTINEL_RE = /^\{\{\s*[\w.]+\s*\}\}$/;

export function isDynamicSentinel(value: string): boolean {
  return DYNAMIC_SENTINEL_RE.test(value.trim());
}
