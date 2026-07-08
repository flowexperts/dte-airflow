"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Input } from "./form";

interface FieldOption {
  name: string;
  type?: string;
}

interface FieldPickerProps {
  value: string;
  onChange: (v: string) => void;
  options: FieldOption[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}

/**
 * Themed combobox — Input + our own popover list, not a native <datalist>
 * (browsers style datalist themselves, ignoring our tokens).
 */
export function FieldPicker({
  value,
  onChange,
  options,
  placeholder,
  className,
  disabled,
}: FieldPickerProps) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = value.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.name.toLowerCase().includes(q));
  }, [options, value]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (highlight >= filtered.length) setHighlight(0);
  }, [filtered, highlight]);

  const select = (name: string) => {
    onChange(name);
    setOpen(false);
    inputRef.current?.blur();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
      setOpen(true);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      if (filtered[highlight]) {
        e.preventDefault();
        select(filtered[highlight].name);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <Input
        ref={inputRef}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          if (!open) setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
      />
      {open && filtered.length > 0 && (
        <div
          className="absolute z-30 top-full left-0 right-0 mt-1 max-h-56 overflow-auto border border-border rounded-[var(--radius)] bg-surface shadow-lg"
          role="listbox"
        >
          {filtered.map((o, i) => (
            <button
              key={o.name}
              type="button"
              role="option"
              aria-selected={i === highlight}
              onMouseDown={(e) => {
                e.preventDefault();
                select(o.name);
              }}
              onMouseEnter={() => setHighlight(i)}
              className={cn(
                "w-full flex items-center justify-between gap-3 px-2.5 py-1.5 text-left font-mono text-[12.5px]",
                i === highlight ? "bg-[color:var(--accent-tint)] text-text" : "text-text hover:bg-hover",
              )}
            >
              <span>{o.name}</span>
              {o.type && (
                <span className="text-subtle text-[11px]">{o.type}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
