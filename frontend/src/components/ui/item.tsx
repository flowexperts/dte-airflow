import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function Item({
  glyph,
  label,
  path,
  tag,
  className,
}: {
  glyph?: ReactNode;
  label: ReactNode;
  path?: ReactNode;
  tag?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-[28px_1fr_auto] gap-2.5 items-center px-3.5 py-3 border-b border-border last:border-b-0 hover:bg-hover transition-colors",
        className,
      )}
    >
      <div className="size-6 border border-border-2 rounded-sm bg-code-bg flex items-center justify-center font-mono text-[11px] text-accent">
        {glyph}
      </div>
      <div className="min-w-0">
        <div className="text-[13px] font-medium">{label}</div>
        {path && (
          <div className="font-mono text-[11px] text-subtle mt-0.5 truncate">
            {path}
          </div>
        )}
      </div>
      {tag}
    </div>
  );
}

type TagVariant = "default" | "output";

export function Tag({
  children,
  variant = "default",
  className,
}: {
  children: ReactNode;
  variant?: TagVariant;
  className?: string;
}) {
  const color = variant === "output" ? "var(--green)" : "var(--gold)";
  const bg =
    variant === "output"
      ? "color-mix(in srgb, var(--green) 12%, transparent)"
      : "color-mix(in srgb, var(--gold) 12%, transparent)";
  return (
    <span
      className={cn(
        "font-mono text-[9.5px] tracking-[0.15em] uppercase px-1.5 py-0.5 rounded-sm",
        className,
      )}
      style={{ color, background: bg }}
    >
      {children}
    </span>
  );
}
