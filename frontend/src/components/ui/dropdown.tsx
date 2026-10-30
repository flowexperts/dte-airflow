import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "./portal-host";
import { useMounted } from "./use-mounted";
import { cn } from "@/lib/cn";
import { usePopoverPosition } from "./use-popover-position";

export type DropdownOption<T extends string> =
  | { kind?: "option"; value: T; label: ReactNode; meta?: ReactNode; disabled?: boolean }
  | { kind: "action"; onSelect: () => void; label: ReactNode }
  | { kind: "divider" };

interface DropdownProps<T extends string> {
  value: T | "";
  onChange: (v: T) => void;
  options: DropdownOption<T>[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}

const triggerBase =
  "w-full flex items-center justify-between gap-2 bg-bg text-text border border-border rounded-[var(--radius)] px-2.5 py-1.5 text-[13.5px] font-[family-name:var(--font-ui)] hover:border-accent transition-colors focus:outline-none focus:border-accent";

export function Dropdown<T extends string>({
  value,
  onChange,
  options,
  placeholder = "— select —",
  className,
  disabled,
}: DropdownProps<T>) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const mounted = useMounted();

  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const selectable = useMemo(
    () =>
      options
        .map((o, i) => ({ o, i }))
        .filter(({ o }) => o.kind !== "divider" && !("disabled" in o && o.disabled)),
    [options],
  );

  const currentLabel = useMemo(() => {
    for (const o of options) {
      if ((o.kind ?? "option") === "option" && "value" in o && o.value === value) {
        return o.label;
      }
    }
    return null;
  }, [options, value]);

  const pos = usePopoverPosition(triggerRef, open);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (containerRef.current?.contains(t) || popoverRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const commit = (idx: number) => {
    const opt = options[idx];
    if (!opt) return;
    if (opt.kind === "action") {
      opt.onSelect();
      setOpen(false);
      return;
    }
    if ((opt.kind ?? "option") === "option" && "value" in opt) {
      onChange(opt.value);
      setOpen(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        setOpen(true);
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const cur = selectable.findIndex((s) => s.i === highlight);
      const next = selectable[Math.min(cur + 1, selectable.length - 1)];
      if (next) setHighlight(next.i);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const cur = selectable.findIndex((s) => s.i === highlight);
      const prev = selectable[Math.max(cur - 1, 0)];
      if (prev) setHighlight(prev.i);
    } else if (e.key === "Enter") {
      e.preventDefault();
      commit(highlight);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onKeyDown}
        className={cn(triggerBase, disabled && "opacity-50 cursor-not-allowed")}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={cn("truncate text-left", !currentLabel && "text-subtle")}>
          {currentLabel ?? placeholder}
        </span>
        <svg aria-hidden viewBox="0 0 12 12" className="h-3 w-3 shrink-0 text-subtle">
          <path
            d="M3 5l3 3 3-3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {mounted &&
        open &&
        pos &&
        createPortal(
          <div
            ref={popoverRef}
            style={pos.style}
            className="overflow-auto border border-border rounded-[var(--radius)] bg-surface shadow-lg py-1"
            role="listbox"
          >
            {options.map((o, i) => {
              if (o.kind === "divider") {
                return <div key={`div-${i}`} className="my-1 border-t border-border" />;
              }
              const isAction = o.kind === "action";
              const isDisabled = "disabled" in o && o.disabled;
              const active = i === highlight;
              return (
                <button
                  key={i}
                  type="button"
                  role="option"
                  aria-selected={active}
                  disabled={isDisabled}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    if (!isDisabled) commit(i);
                  }}
                  onMouseEnter={() => !isDisabled && setHighlight(i)}
                  className={cn(
                    "w-full flex items-center justify-between gap-3 px-2.5 py-1.5 text-left text-[13px]",
                    isAction && "text-accent font-medium",
                    !isAction && "text-text",
                    active && !isDisabled && "bg-[color:var(--accent-tint)]",
                    isDisabled && "opacity-50 cursor-not-allowed",
                  )}
                >
                  <span className="truncate">{o.label}</span>
                  {"meta" in o && o.meta && (
                    <span className="font-mono text-[11px] text-subtle shrink-0">{o.meta}</span>
                  )}
                </button>
              );
            })}
          </div>,
          portalHost(),
        )}
    </div>
  );
}
