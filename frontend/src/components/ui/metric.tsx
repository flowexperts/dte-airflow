import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function MetricRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 border border-border rounded-[var(--radius)] bg-surface overflow-hidden",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Metric({
  label,
  value,
  unit,
  tone = "default",
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  tone?: "default" | "ok" | "warn" | "err";
  className?: string;
}) {
  const color =
    tone === "ok" ? "text-green" : tone === "warn" ? "text-gold" : tone === "err" ? "text-red" : "";
  return (
    <div
      className={cn(
        "px-5 py-4 border-r last:border-r-0 border-b sm:border-b-0 lg:border-b-0 border-border",
        className,
      )}
    >
      <div className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle mb-1.5">
        {label}
      </div>
      <div
        className={cn(
          "text-[28px] font-medium leading-tight tracking-[-0.01em] tabular-nums",
          color,
        )}
      >
        {value}
        {unit && (
          <span className="font-mono text-[11px] font-normal tracking-[0.1em] uppercase text-subtle ml-1.5">
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}
