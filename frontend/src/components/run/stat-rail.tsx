import type { ReactNode } from "react";
import { Panel } from "@/components/ui";
import { toneVar, type Tone } from "./helpers";

export function StatRow({
  label,
  value,
  tone,
  small,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: Tone;
  /** Long values (timestamps) drop a size rather than wrap. */
  small?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-border last:border-b-0">
      <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle shrink-0">
        {label}
      </span>
      <span
        className={`tabular-nums text-right ${small ? "text-[12.5px] font-normal" : "text-[15px] font-medium"}`}
        style={tone ? { color: toneVar[tone] } : undefined}
      >
        {value}
      </span>
    </div>
  );
}

/** Compact vertical rail. Quality runs use this instead of the wide metric tiles
 *  — their numbers are context, not the headline. */
export function StatRail({ children }: { children: ReactNode }) {
  return <Panel>{children}</Panel>;
}
