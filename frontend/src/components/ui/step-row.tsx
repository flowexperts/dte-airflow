import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function StepRow({
  index,
  op,
  title,
  children,
  onGrip,
  className,
}: {
  index: number | string;
  op: string;
  title: ReactNode;
  children?: ReactNode;
  onGrip?: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-[36px_1fr_auto] border-b border-border last:border-b-0 hover:bg-hover transition-colors group",
        className,
      )}
    >
      <div className="py-3 text-center font-mono text-[11px] text-subtle border-r border-border group-hover:text-accent">
        {index}
      </div>
      <div className="py-3 px-3.5 min-w-0">
        <div className="flex items-center gap-2.5 mb-1.5">
          <span className="font-mono text-[10px] font-bold tracking-[0.15em] uppercase text-accent px-1.5 py-0.5 rounded-sm bg-[color:var(--accent-tint)]">
            {op}
          </span>
          <span className="text-[14.5px] font-medium text-text truncate">
            {title}
          </span>
        </div>
        {children}
      </div>
      <button
        type="button"
        onClick={onGrip}
        className="px-3 text-subtle hover:text-accent cursor-grab border-l border-border text-sm flex items-center"
        aria-label="Reorder step"
      >
        ⋮⋮
      </button>
    </div>
  );
}

export function ExprCode({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <code
      className={cn(
        "inline-block max-w-full overflow-x-auto whitespace-nowrap",
        "font-mono text-[12px] text-muted",
        "bg-code-bg border border-border rounded-sm px-2.5 py-1.5",
        className,
      )}
    >
      {children}
    </code>
  );
}

export function ExprToken({
  as,
  children,
}: {
  as: "field" | "value" | "op";
  children: ReactNode;
}) {
  const color =
    as === "field" ? "text-gold" : as === "value" ? "text-green" : "text-accent";
  return <span className={color}>{children}</span>;
}

export function KV({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap gap-y-1 gap-x-3 font-mono text-[11.5px] text-subtle">
      {children}
    </div>
  );
}

export function KVItem({
  label,
  value,
}: {
  label: ReactNode;
  value?: ReactNode;
}) {
  return (
    <span>
      <b className="text-muted font-normal">{label}</b>
      {value !== undefined && <> {value}</>}
    </span>
  );
}

export function AddStep({
  onClick,
  label = "Add step",
}: {
  onClick?: () => void;
  /** Quality pipelines add checks, not steps. */
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-center py-3 px-3.5 border-t border-dashed border-border font-medium text-xs text-subtle hover:text-accent hover:bg-[color:var(--accent-tint)] transition-colors"
    >
      <span className="text-accent font-bold mr-1">+</span> {label}
    </button>
  );
}
