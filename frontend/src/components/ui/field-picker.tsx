"use client";

import { useId } from "react";
import { cn } from "@/lib/cn";
import { Input } from "./form";

interface FieldPickerProps {
  value: string;
  onChange: (v: string) => void;
  options: { name: string; type?: string }[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}

/**
 * Free-text input with a datalist of known field names for autocomplete.
 * Falls back to a plain Input if options is empty.
 */
export function FieldPicker({
  value,
  onChange,
  options,
  placeholder,
  className,
  disabled,
}: FieldPickerProps) {
  const id = useId();
  return (
    <>
      <Input
        list={options.length ? id : undefined}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={cn(className)}
        disabled={disabled}
      />
      {options.length > 0 && (
        <datalist id={id}>
          {options.map((o) => (
            <option key={o.name} value={o.name}>
              {o.type ?? ""}
            </option>
          ))}
        </datalist>
      )}
    </>
  );
}
