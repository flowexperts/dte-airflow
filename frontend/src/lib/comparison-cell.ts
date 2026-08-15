/**
 * How one sweep cell is named wherever it appears.
 *
 * Lives here rather than in `comparison-grid.tsx` because the grid imports
 * the promote chooser, which needs the same labels — importing back from the
 * grid would be a cycle. More importantly the card and the dropdown must read
 * identically: picking "claude · claude-haiku-4-5" from a list has to be
 * unambiguously the card the user was looking at when they decided.
 */
import type { ComparisonCell } from "./api";

export function cellLabel(cell: ComparisonCell): string {
  const c = cell.cell ?? {};
  const parts = [c.provider, c.model].filter(Boolean) as string[];
  return parts.length > 0 ? parts.join(" · ") : cell.pipeline_id;
}
