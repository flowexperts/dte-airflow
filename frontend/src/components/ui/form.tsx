import { cn } from "@/lib/cn";
import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {label && (
        <label className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
          {label}
        </label>
      )}
      {children}
      {hint && !error && (
        <span className="text-[11.5px] text-subtle">{hint}</span>
      )}
      {error && <span className="text-[11.5px] text-red">{error}</span>}
    </div>
  );
}

const inputBase =
  "w-full bg-bg text-text border border-border rounded-[var(--radius)] px-2.5 py-1.5 text-[13.5px] font-[family-name:var(--font-ui)] placeholder:text-subtle focus:outline-none focus:border-accent transition-colors";

export function Input({
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(inputBase, className)} {...rest} />;
}

export function Textarea({
  className,
  rows = 3,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      rows={rows}
      className={cn(inputBase, "font-mono text-[12.5px] leading-[1.5]", className)}
      {...rest}
    />
  );
}

interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: SegmentedOption<T>[];
  className?: string;
}) {
  return (
    <div
      className={cn(
        "inline-flex border border-border rounded-[var(--radius)] bg-surface p-0.5",
        className,
      )}
      role="radiogroup"
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "px-3 py-1 text-[12.5px] font-medium rounded-[3px] transition-colors",
              active
                ? "bg-[color:var(--accent-tint)] text-accent"
                : "text-muted hover:text-text",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
