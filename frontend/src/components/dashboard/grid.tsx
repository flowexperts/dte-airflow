"use client";

/**
 * The tile grid (plan 064).
 *
 * A 12-column CSS grid with tiles flowing in array order. Widths are spans
 * of 4 / 6 / 12, which is why `DashboardTile.width` is an enum: free
 * integers leave gaps no layout code can close, and free x/y coordinates
 * would need collision handling before they were usable at all.
 *
 * Ordering is the array, so "move up" is a swap — the same affordance
 * `StepsPanel` uses for steps. Drag-and-drop is deferred until tile counts
 * make arrows tedious.
 */
import type { DashboardTile } from "@/lib/api";
import { Tile } from "./tile";

const SPAN: Record<number, string> = {
  4: "md:col-span-4",
  6: "md:col-span-6",
  12: "md:col-span-12",
};

export function DashboardGrid({
  tiles,
  renderOverlay,
}: {
  tiles: DashboardTile[];
  /** Edit-mode controls drawn above each tile. Omitted in read mode so the
   *  view surface carries no affordances it cannot act on. */
  renderOverlay?: (tile: DashboardTile, index: number) => React.ReactNode;
}) {
  if (tiles.length === 0) {
    return (
      <div className="border border-dashed border-border rounded-[var(--radius)] py-12 text-center text-[12.5px] text-subtle">
        No tiles yet. Add one to start drawing.
      </div>
    );
  }

  return (
    // Single column below md: a 4-span chart on a phone is unreadable, and
    // the axis labels collide long before the tile does.
    <div className="grid grid-cols-1 md:grid-cols-12 gap-3">
      {tiles.map((tile, i) => (
        <div key={tile.id} className={SPAN[tile.width] ?? SPAN[6]}>
          {renderOverlay?.(tile, i)}
          <Tile tile={tile} />
        </div>
      ))}
    </div>
  );
}
