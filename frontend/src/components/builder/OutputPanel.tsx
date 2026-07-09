"use client";

import { useState } from "react";
import {
  Field,
  FieldMultiSelect,
  Input,
  Panel,
  PanelHead,
  Segmented,
} from "@/components/ui";
import type { JsonFileOutput, OutputField } from "@/lib/api";
import { useSchemas } from "./schema-context";

type Mode = "all" | "keep" | "drop";

export function OutputPanel({
  output,
  onChange,
}: {
  output: JsonFileOutput;
  onChange: (next: JsonFileOutput) => void;
}) {
  const { allFields } = useSchemas();

  // Local UI mode. Backend only stores output.fields (a whitelist), so
  // "drop" is compiled at the moment we commit changes: fields = allFields - dropped.
  const [mode, setMode] = useState<Mode>(
    (output.fields ?? []).length === 0 ? "all" : "keep",
  );
  const [dropped, setDropped] = useState<string[]>([]);
  const known = allFields.map((f) => f.name);
  const currentFields: OutputField[] = output.fields ?? [];

  const setFields = (next: OutputField[]) =>
    onChange({ ...output, fields: next });

  // ---- keep mode helpers ----
  const keepNames = currentFields.map((f) => f.field);
  const setKeep = (names: string[]) => {
    // preserve existing aliases where possible
    const prev = new Map(currentFields.map((f) => [f.field, f.alias ?? null]));
    setFields(names.map((n) => ({ field: n, alias: prev.get(n) ?? null })));
  };
  const setAlias = (field: string, alias: string) =>
    setFields(
      currentFields.map((f) =>
        f.field === field ? { ...f, alias: alias || null } : f,
      ),
    );

  // ---- drop mode helpers ----
  const applyDrop = (nextDropped: string[]) => {
    setDropped(nextDropped);
    if (known.length === 0) {
      setFields([]); // no schema yet — nothing to compute against
      return;
    }
    const keep = known.filter((n) => !nextDropped.includes(n));
    setFields(keep.map((n) => ({ field: n, alias: null })));
  };

  const changeMode = (m: Mode) => {
    setMode(m);
    if (m === "all") {
      setFields([]);
      setDropped([]);
    } else if (m === "keep") {
      // starting fresh from empty; user picks what to keep
      setFields([]);
    } else if (m === "drop") {
      setDropped([]);
      setFields([]);
    }
  };

  return (
    <Panel>
      <PanelHead label="Output" />
      <div className="p-4 grid gap-4">
        <Field
          label="Path"
          hint="local or bucket path where the result is written"
        >
          <Input
            value={output.path ?? ""}
            onChange={(e) => onChange({ ...output, path: e.target.value })}
            placeholder="./out/result.json"
          />
        </Field>

        <div className="grid gap-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
              Fields
            </span>
            <Segmented<Mode>
              value={mode}
              onChange={changeMode}
              options={[
                { value: "all",  label: "Keep all" },
                { value: "keep", label: "Select fields" },
                { value: "drop", label: "Drop fields" },
              ]}
            />
          </div>

          {mode === "all" && (
            <p className="font-mono text-[11.5px] text-subtle">
              Every field from the last step is written to the output.
            </p>
          )}

          {mode === "keep" && (
            <div className="space-y-3">
              <FieldMultiSelect
                value={keepNames}
                onChange={setKeep}
                options={allFields}
                placeholder="add field to keep…"
              />
              {currentFields.length > 0 && (
                <div className="space-y-1.5">
                  <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
                    Aliases (optional)
                  </div>
                  {currentFields.map((f) => (
                    <div
                      key={f.field}
                      className="grid grid-cols-[1fr_16px_1fr] gap-2 items-center"
                    >
                      <span className="font-mono text-[12.5px] text-text px-2.5 py-1.5 border border-border rounded bg-code-bg">
                        {f.field}
                      </span>
                      <span className="text-subtle text-center">→</span>
                      <Input
                        value={f.alias ?? ""}
                        onChange={(e) => setAlias(f.field, e.target.value)}
                        placeholder={f.field}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {mode === "drop" && (
            <div className="space-y-2">
              {known.length === 0 ? (
                <p className="font-mono text-[11.5px] text-subtle">
                  Infer the source schema first — Drop mode needs to know what
                  fields exist to compute the complement.
                </p>
              ) : (
                <>
                  <FieldMultiSelect
                    value={dropped}
                    onChange={applyDrop}
                    options={allFields}
                    placeholder="add field to drop…"
                  />
                  <p className="font-mono text-[11px] text-subtle">
                    Kept: {currentFields.map((f) => f.field).join(", ") || "—"}
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}
