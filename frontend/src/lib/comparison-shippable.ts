/**
 * Which configs in a comparison can be shipped, and why the rest cannot.
 *
 * Promoting copies a config verbatim into a transform pipeline that writes
 * real output. Not every cell in a comparison is a candidate for that, and
 * the interesting exclusion is not the obvious one:
 *
 * A run whose every provider call failed is `completed` and green, because
 * `on_error: null` fills nulls rather than failing the run. It looks
 * identical to a config that ran clean. Shipping it ships a pipeline that
 * produces empty columns on every document — the silent-zero failure this
 * whole harness keeps closing.
 *
 * Excluded cells are *offered as excluded* rather than dropped: a missing
 * option reads as a bug, while "every row errored" is the most useful thing
 * the page can say at that moment.
 *
 * Nothing here marks a preferred cell. Without labels the comparison
 * computes no ranking, and with them it computes ties rather than winners —
 * so which config to ship is the user's judgment, and the UI must not
 * quietly make it for them.
 */
import type { ComparisonCell } from "./api";

export interface ShippableCell {
  cell: ComparisonCell;
  shippable: boolean;
  /** Why not, phrased for display. `null` when shippable. */
  reason: string | null;
}

function why(cell: ComparisonCell): string | null {
  if (cell.status === "failed") return "the run did not finish";
  if (cell.status === "pending" || cell.status === "running") {
    return "still running";
  }
  if (cell.documents === 0) return "produced no documents";
  // Not `>= documents`: a cell can error on more rows than it produced only
  // if the counts disagree, and in that case we would rather offer it and
  // let promote's own validation speak than hide it on arithmetic.
  if (cell.documents > 0 && cell.error_count >= cell.documents) {
    return "every row errored";
  }
  return null;
}

/** Input order is preserved so the dropdown reads in the same order as the cards. */
export function shippableCells(cells: ComparisonCell[]): ShippableCell[] {
  return cells.map((cell) => {
    const reason = why(cell);
    return { cell, shippable: reason === null, reason };
  });
}

export function hasShippableCell(cells: ComparisonCell[]): boolean {
  return shippableCells(cells).some((c) => c.shippable);
}
