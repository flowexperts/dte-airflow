"use client";

import {
  Dropdown,
  Field,
  Input,
  Panel,
  PanelHead,
  type DropdownOption,
} from "@/components/ui";
import {
  FILE_OUTPUT_EXT,
  FILE_OUTPUT_TYPES,
  emptyFileOutput,
  type FileOutputTarget,
  type FileOutputType,
} from "@/lib/api";

/**
 * Output only describes where the result is written. Field selection
 * lives in the ordered steps (op: "select") — it's a mid-pipeline concern
 * that composes with everything else.
 *
 * All three inline-editable output types (json_file / csv_file /
 * excel_file) share `{ path, fields? }` — the type picker toggles the
 * discriminant while preserving `path`.
 */
export function OutputPanel({
  output,
  onChange,
}: {
  output: FileOutputTarget;
  onChange: (next: FileOutputTarget) => void;
}) {
  const typeOptions: DropdownOption<FileOutputType>[] = FILE_OUTPUT_TYPES.map(
    (t) => ({
      value: t,
      label: TYPE_LABEL[t],
      meta: FILE_OUTPUT_EXT[t],
    }),
  );

  const setType = (t: FileOutputType) => {
    if (t === output.type) return;
    onChange(emptyFileOutput(t, output.path ?? ""));
  };

  return (
    <Panel>
      <PanelHead label="Output" />
      <div className="p-4 grid gap-3">
        <Field label="Type" hint="chooses the writer (JSON, CSV, or XLSX)">
          <Dropdown<FileOutputType>
            value={output.type}
            onChange={setType}
            options={typeOptions}
          />
        </Field>
        <Field
          label="Path"
          hint={`local or bucket path where the result is written; expected extension ${FILE_OUTPUT_EXT[output.type]}`}
        >
          <Input
            value={output.path ?? ""}
            onChange={(e) => onChange({ ...output, path: e.target.value })}
            placeholder={`./out/result${FILE_OUTPUT_EXT[output.type]}`}
          />
        </Field>
      </div>
    </Panel>
  );
}

const TYPE_LABEL: Record<FileOutputType, string> = {
  json_file: "JSON file",
  csv_file: "CSV file",
  excel_file: "Excel (.xlsx)",
};
