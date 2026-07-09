import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

type Status = "ok" | "running" | "failed" | "pending";

const styles: Record<Status, { color: string; bg: string; pulse: boolean }> = {
  ok:       { color: "var(--green)", bg: "color-mix(in srgb, var(--green) 12%, transparent)", pulse: false },
  running:  { color: "var(--gold)",  bg: "color-mix(in srgb, var(--gold) 14%, transparent)",  pulse: true  },
  failed:   { color: "var(--red)",   bg: "color-mix(in srgb, var(--red) 12%, transparent)",   pulse: false },
  pending:  { color: "var(--subtle)",bg: "var(--surface-2)", pulse: false },
};

const labels: Record<Status, string> = {
  ok: "Completed",
  running: "Running",
  failed: "Failed",
  pending: "Pending",
};

export function Pill({
  status,
  children,
  className,
}: {
  status: Status;
  children?: ReactNode;
  className?: string;
}) {
  const s = styles[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[10px] text-[11.5px] font-medium leading-tight",
        className,
      )}
      style={{ color: s.color, background: s.bg }}
    >
      <span
        className={cn("size-1.5 rounded-full shrink-0", s.pulse && "animate-pulse-dot")}
        style={{ background: "currentColor" }}
      />
      {children ?? labels[status]}
    </span>
  );
}
