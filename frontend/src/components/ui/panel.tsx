import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function Panel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "border border-border rounded-[var(--radius)] bg-surface overflow-hidden",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function PanelHead({
  label,
  count,
  className,
}: {
  label: string;
  count?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between px-3.5 py-2.5 border-b border-border",
        "font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle",
        className,
      )}
    >
      <span>{label}</span>
      {count !== undefined && (
        <span className="font-[family-name:var(--font-ui)] text-xs tracking-normal text-text normal-case">
          {count}
        </span>
      )}
    </div>
  );
}
