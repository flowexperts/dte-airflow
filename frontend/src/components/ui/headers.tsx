import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function PageHeader({
  title,
  sub,
  lede,
  actions,
  className,
}: {
  title: ReactNode;
  sub?: ReactNode;
  lede?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-6 px-14 py-6 border-b border-border",
        className,
      )}
    >
      <div>
        <h1 className="flex items-baseline gap-2.5 text-[26px] font-medium tracking-[-0.005em] leading-tight m-0">
          {title}
          {sub && (
            <span className="font-mono text-[11px] tracking-[0.1em] uppercase text-subtle font-normal">
              {sub}
            </span>
          )}
        </h1>
        {lede && <p className="text-[13px] text-muted mt-1 mb-0">{lede}</p>}
      </div>
      {actions && <div className="flex gap-2 items-center">{actions}</div>}
    </div>
  );
}

export function SectionHead({
  title,
  count,
  actions,
  className,
}: {
  title: ReactNode;
  count?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between mb-4", className)}>
      <h2 className="flex items-baseline gap-2.5 text-[17px] font-medium m-0">
        {title}
        {count !== undefined && (
          <span className="font-mono text-[11px] tracking-[0.06em] text-subtle font-normal">
            {count}
          </span>
        )}
      </h2>
      {actions && <div className="flex gap-1.5 items-center">{actions}</div>}
    </div>
  );
}
