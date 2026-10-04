import { useLayoutEffect, useState, type RefObject } from "react";

export interface PopoverPosition {
  /** Ready to spread onto the portaled element's `style`. */
  style: {
    position: "fixed";
    left: number;
    top?: number;
    bottom?: number;
    minWidth: number;
    maxHeight: number;
    zIndex: number;
  };
  /** True when the popover opens upward. Callers that draw a pointer or
   *  round one edge need to know which way it went. */
  flipped: boolean;
}

const GAP = 4;
const EDGE = 8;

/**
 * Position a portaled popover against a trigger.
 *
 * Every popover in the kit portals to `<body>` so it escapes `Panel`'s
 * `overflow-hidden`. That solved clipping but left three problems this hook
 * fixes, all of which bite hardest in a narrow column:
 *
 * - **Flip.** A hard-coded `top: bottom + 4` puts a 288px menu below the fold
 *   for any trigger in the lower third of the viewport. We open upward when
 *   there's more room there.
 * - **Clamp.** `left` is kept inside the viewport, and `maxHeight` is capped to
 *   the space actually available so the popover's own `overflow-auto` scrolls
 *   instead of the box running off-screen.
 * - **minWidth.** Popovers inherited the trigger's width, so a picker in a
 *   `1.4fr` grid track produced a ~150px menu — too narrow for a nested field
 *   path once indentation and a checkbox are subtracted. `minWidth` decouples
 *   the menu from the trigger; it never shrinks below it.
 *
 * Recomputes on scroll (capture, so nested scroll containers count) and resize,
 * matching the behaviour it replaces.
 */
export function usePopoverPosition(
  triggerRef: RefObject<HTMLElement | null>,
  open: boolean,
  opts?: {
    /** Lower bound for the popover's width. Default 200. */
    minWidth?: number;
    /** The popover's natural max height — the cap it would use with infinite
     *  room. Default 288 (`max-h-72`). */
    preferredMaxHeight?: number;
  },
): PopoverPosition | null {
  const [pos, setPos] = useState<PopoverPosition | null>(null);
  const minWidth = opts?.minWidth ?? 200;
  const preferred = opts?.preferredMaxHeight ?? 288;

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }

    const compute = () => {
      const r = triggerRef.current?.getBoundingClientRect();
      if (!r) return;

      const width = Math.max(r.width, minWidth);
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      // Keep the box on screen horizontally, but never push it past the left
      // edge when the viewport is narrower than the popover itself.
      const left = Math.max(EDGE, Math.min(r.left, vw - width - EDGE));

      const below = vh - r.bottom - GAP - EDGE;
      const above = r.top - GAP - EDGE;
      // Only flip when below genuinely can't hold the menu and above is better.
      const flipped = below < Math.min(preferred, above) && above > below;
      const maxHeight = Math.max(120, Math.min(preferred, flipped ? above : below));

      setPos({
        flipped,
        style: {
          position: "fixed",
          left,
          ...(flipped
            ? { bottom: vh - r.top + GAP }
            : { top: r.bottom + GAP }),
          minWidth: width,
          maxHeight,
          zIndex: 1000,
        },
      });
    };

    compute();
    window.addEventListener("scroll", compute, true);
    window.addEventListener("resize", compute);
    return () => {
      window.removeEventListener("scroll", compute, true);
      window.removeEventListener("resize", compute);
    };
  }, [open, minWidth, preferred, triggerRef]);

  return pos;
}
