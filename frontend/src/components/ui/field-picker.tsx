"use client";

import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { Input } from "./form";
import { FieldTreePicker } from "./field-tree-picker";

interface FieldOption {
  name: string;
  type?: string;
}

interface FieldPickerProps {
  value: string;
  onChange: (v: string) => void;
  options: FieldOption[];
  placeholder?: string | undefined;
  className?: string | undefined;
  disabled?: boolean | undefined;
  variant?: "flat" | "tree" | undefined;
}

/**
 * Themed combobox — Input + a portaled popover.
 * Portaling to <body> is what lets the dropdown escape clipping ancestors
 * like Panel (which uses overflow-hidden for its rounded corners).
 */
export function FieldPicker(props: FieldPickerProps) {
  if (props.variant === "tree") {
    return (
      <FieldTreePicker
        mode="single"
        value={props.value}
        onChange={props.onChange}
        options={props.options}
        placeholder={props.placeholder}
        className={props.className}
        disabled={props.disabled}
      />
    );
  }
  return <FieldPickerFlat {...props} />;
}

function FieldPickerFlat({
  value,
  onChange,
  options,
  placeholder,
  className,
  disabled,
}: FieldPickerProps) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [pos, setPos] = useState<{ left: number; top: number; width: number } | null>(null);
  const [mounted, setMounted] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);

  const filtered = useMemo(() => {
    const q = value.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.name.toLowerCase().includes(q));
  }, [options, value]);

  // Position/reposition when opening, on scroll, and on resize.
  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const compute = () => {
      const r = inputRef.current?.getBoundingClientRect();
      if (!r) return;
      setPos({ left: r.left, top: r.bottom + 4, width: r.width });
    };
    compute();
    window.addEventListener("scroll", compute, true);
    window.addEventListener("resize", compute);
    return () => {
      window.removeEventListener("scroll", compute, true);
      window.removeEventListener("resize", compute);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        containerRef.current?.contains(target) ||
        popoverRef.current?.contains(target)
      ) {
        return;
      }
      setOpen(false);
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
      {mounted && open && pos && filtered.length > 0 &&
        createPortal(
          <div
            ref={popoverRef}
            style={{
              position: "fixed",
              left: pos.left,
              top: pos.top,
              width: pos.width,
              zIndex: 1000,
            }}
            className="max-h-56 overflow-auto border border-border rounded-[var(--radius)] bg-surface shadow-lg"
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
          </div>,
          document.body,
        )}
    </div>
  );
}
