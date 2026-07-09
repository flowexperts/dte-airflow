"use client";

import { Field, Input, Panel, PanelHead } from "@/components/ui";
import type { JsonFileOutput } from "@/lib/api";

/**
 * Output only describes where the result is written. Field selection
 * lives in the ordered steps (op: "select") — it's a mid-pipeline concern
 * that composes with everything else.
 */
export function OutputPanel({
  output,
  onChange,
}: {
  output: JsonFileOutput;
  onChange: (next: JsonFileOutput) => void;
}) {
  return (
    <Panel>
      <PanelHead label="Output" />
      <div className="p-4 grid gap-3">
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
      </div>
    </Panel>
  );
}
