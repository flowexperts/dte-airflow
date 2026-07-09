import { cn } from "@/lib/cn";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "default" | "primary" | "ghost";
type Size = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  kbd?: string;
  leadingIcon?: ReactNode;
}

const base =
  "inline-flex items-center gap-1.5 rounded-[var(--radius)] font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none";

const variants: Record<Variant, string> = {
  default:
    "bg-surface text-text border border-border-2 hover:bg-hover",
  primary:
    "bg-accent border border-accent text-white hover:bg-accent-h hover:border-accent-h",
  ghost:
    "bg-transparent border border-transparent text-muted hover:text-text hover:bg-hover",
};

const sizes: Record<Size, string> = {
  sm: "px-2 py-1 text-[11.5px]",
  md: "px-3 py-1.5 text-[12.5px]",
};

export function Button({
  variant = "default",
  size = "md",
  kbd,
  leadingIcon,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button className={cn(base, variants[variant], sizes[size], className)} {...rest}>
      {leadingIcon}
      {children}
      {kbd ? <Kbd className="ml-1">{kbd}</Kbd> : null}
    </button>
  );
}

export function Kbd({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "font-mono text-[10px] px-1 py-px rounded-sm opacity-70",
        "bg-hover text-current",
        className,
      )}
    >
      {children}
    </span>
  );
}
