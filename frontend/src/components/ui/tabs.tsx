import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface TabOption<T extends string> {
  value: T;
  label: ReactNode;
  /** Right-aligned count or status, shown muted next to the label. */
  badge?: ReactNode;
}

/**
 * Tab strip for switching panes that occupy the same space.
 *
 * `Segmented` is the sibling control and the visual reference; the difference
 * is intent. Segmented picks a *mode* for one thing (Basic vs Advanced editing
 * of the same filter). Tabs pick *which thing* you are looking at, where the
 * alternatives are unrelated content — so it is full-width, underlined rather
 * than pill-shaped, and carries per-tab badges.
 *
 * Follows the roving-tabindex ARIA tab pattern: arrow keys move between tabs.
 * Panels are the caller's business — render whichever matches `value`.
 */
export function Tabs<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: TabOption<T>[];
  className?: string;
}) {
  const move = (dir: 1 | -1) => {
    const i = options.findIndex((o) => o.value === value);
    if (i === -1) return;
    const next = options[(i + dir + options.length) % options.length];
    if (next) onChange(next.value);
  };

  return (
    <div
      role="tablist"
      className={cn("flex border-b border-border", className)}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") {
          e.preventDefault();
          move(1);
        } else if (e.key === "ArrowLeft") {
          e.preventDefault();
          move(-1);
        }
      }}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(o.value)}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 px-2 py-2",
              "font-mono text-[10.5px] tracking-[0.15em] uppercase transition-colors",
              // -1px pulls the indicator onto the container's border so the
              // two don't stack into a 2px line.
              "border-b-2 -mb-px",
              active
                ? "border-accent text-accent"
                : "border-transparent text-subtle hover:text-text hover:bg-hover",
            )}
          >
            {o.label}
            {o.badge !== undefined && (
              <span className="font-[family-name:var(--font-ui)] text-[11px] tracking-normal normal-case text-subtle">
                {o.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
