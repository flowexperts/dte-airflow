import { useState } from "react";
import { cn } from "@/lib/cn";
import { FieldPicker } from "./field-picker";
import { FieldTreePicker } from "./field-tree-picker";
import { toDisplay } from "./field-tree";

interface FieldOption {
  name: string;
  type?: string;
}

interface FieldMultiSelectProps {
  value: string[];
  onChange: (v: string[]) => void;
  options: FieldOption[];
  placeholder?: string;
  className?: string;
  variant?: "flat" | "tree";
}

/**
 * Multi-select field picker rendered as chips + a combobox to add another.
 * Emits a string[]. Deduplicates on add. Chip labels use the display form
 * (`order.amount`) in tree mode; internal state remains wire form.
 */
export function FieldMultiSelect({
  value,
  onChange,
  options,
  placeholder = "Add field…",
  className,
  variant = "flat",
}: FieldMultiSelectProps) {
  const [draft, setDraft] = useState("");
  const add = (name: string) => {
    const v = name.trim();
    if (!v || value.includes(v)) return;
    onChange([...value, v]);
    setDraft("");
  };
  const toggle = (wire: string) => {
    if (value.includes(wire)) onChange(value.filter((v) => v !== wire));
    else onChange([...value, wire]);
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
              <span className="text-text">{variant === "tree" ? toDisplay(v) : v}</span>
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
      {variant === "tree" ? (
        <FieldTreePicker
          mode="multi"
          value={value}
          onToggle={toggle}
          options={options}
          placeholder={placeholder}
        />
      ) : (
        <FieldPicker
          value={draft}
          onChange={(v) => {
            setDraft(v);
            if (options.some((o) => o.name === v)) add(v);
          }}
          options={remaining}
          placeholder={placeholder}
        />
      )}
    </div>
  );
}
