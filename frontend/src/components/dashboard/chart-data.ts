/**
 * Reshaping a pipeline preview response into what recharts wants (plan 064).
 *
 * Kept out of the component and pure so it can be tested without a DOM — it
 * is the only part of the chart layer that can be wrong in a way the eye
 * does not catch, because every failure mode renders as a *blank but
 * correct-looking* chart rather than an error.
 */
import type { ChartSpec } from "@/lib/api";

export type Row = Record<string, unknown>;

/**
 * Coerce a preview cell to a number, or null.
 *
 * Preview rows come from `df.to_json()`, and DuckDB's DECIMAL results
 * (`SUM(int)`, `int * 1.1`) serialise as **strings**. Recharts silently
 * ignores a non-numeric value, so without this a summed measure draws an
 * empty plot with a correct-looking axis. `null` is preserved rather than
 * folded to 0: a missing measure is not zero, and recharts renders null as
 * a gap in the line instead of a dive to the baseline.
 */
function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "boolean") return v ? 1 : 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** The category-axis value as a string key, or null when unusable. */
function categoryOf(row: Row, x: string): string | null {
  const raw = row[x];
  if (raw === null || raw === undefined) return null;
  return String(raw);
}

/**
 * Rows in the shape recharts reads: one object per x value, measures as
 * numbers.
 *
 * With `spec.series` set the input is long-form (one row per x × series) and
 * is pivoted to wide (one row per x, one key per series value) — the shape
 * `<Line dataKey="A" />` needs. Without it, rows pass through with their y
 * fields coerced.
 *
 * First-seen order of x is preserved in both paths. The pipeline's own
 * `sort` step is what ordered these rows; re-sorting here would quietly
 * override a deliberate choice, and for a date axis it would sort
 * lexically.
 */
export function chartData(rows: Row[], spec: ChartSpec): Row[] {
  if (!rows || rows.length === 0) return [];

  const measures = spec.y ?? [];

  // No category axis (number / table kinds): coerce measures, keep the rest.
  if (!spec.x) {
    return rows.map((r) => {
      const out: Row = { ...r };
      for (const m of measures) out[m] = toNumber(r[m]);
      return out;
    });
  }

  const x = spec.x;

  if (!spec.series) {
    const out: Row[] = [];
    for (const r of rows) {
      const cat = categoryOf(r, x);
      if (cat === null) continue;
      const next: Row = { [x]: cat };
      for (const m of measures) next[m] = toNumber(r[m]);
      out.push(next);
    }
    return out;
  }

  // Long → wide. One measure only: with a series column, the value column is
  // the measure and the series column supplies the key.
  const measure = measures[0];
  if (!measure) return [];
  const byCategory = new Map<string, Row>();
  for (const r of rows) {
    const cat = categoryOf(r, x);
    if (cat === null) continue;
    const name = r[spec.series];
    if (name === null || name === undefined) continue;
    let bucket = byCategory.get(cat);
    if (!bucket) {
      bucket = { [x]: cat };
      byCategory.set(cat, bucket);
    }
    bucket[String(name)] = toNumber(r[measure]);
  }
  return [...byCategory.values()];
}

/**
 * The keys to draw, in the order colours are assigned.
 *
 * Colour follows the series, not its rank, so this order has to be stable
 * across renders — first-seen in the data, which is the pipeline's own
 * order. Sorting by value would repaint every series whenever the numbers
 * moved.
 */
export function seriesNames(rows: Row[], spec: ChartSpec): string[] {
  if (!spec.series) return spec.y ?? [];
  const seen: string[] = [];
  for (const r of rows) {
    const name = r[spec.series];
    if (name === null || name === undefined) continue;
    const key = String(name);
    if (!seen.includes(key)) seen.push(key);
  }
  return seen;
}
