"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";
import { FieldPicker } from "./field-picker";

interface FieldOption {
  name: string;
  type?: string;
}

/**
 * Multi-select field picker rendered as chips + a combobox to add another.
 * Emits a string[]. Deduplicates on add.
 */
export function FieldMultiSelect({
  value,
  onChange,
  options,
  placeholder = "Add field…",
  className,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  options: FieldOption[];
  placeholder?: string;
  className?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = (name: string) => {
    const v = name.trim();
    if (!v || value.includes(v)) return;
    onChange([...value, v]);
    setDraft("");
  };
  const remove = (name: string) => onChange(value.filter((v) => v !== name));

  const remaining = options.filter((o) => !value.includes(o.name));

  return (
    <div className={cn("space-y-1.5", className)}>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((v) => (
            <span
              key={v}
              className="inline-flex items-center gap-1.5 font-mono text-[11.5px] pl-2 pr-1 py-0.5 rounded border border-border-2 bg-code-bg"
            >
              <span className="text-text">{v}</span>
              <button
                type="button"
                onClick={() => remove(v)}
                className="text-subtle hover:text-red text-[13px] leading-none"
                aria-label={`Remove ${v}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <FieldPicker
        value={draft}
        onChange={(v) => {
          setDraft(v);
          if (options.some((o) => o.name === v)) add(v);
        }}
        options={remaining}
        placeholder={placeholder}
      />
    </div>
  );
}
