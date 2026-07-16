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

  const expectedExt = FILE_OUTPUT_EXT[output.type];

  /** Blur-time autofill: if the user typed a bare filename (no
   *  extension), append the canonical one. Never rewrite an extension
   *  the user already typed — even a wrong one — since that's their
   *  intent. The backend validator will reject a genuine mismatch. */
  const onPathBlur = () => {
    const p = (output.path ?? "").trim();
    if (!p) return;
    const tail = p.split("/").pop() ?? "";
    const hasExt = tail.includes(".") && !tail.endsWith(".");
    if (!hasExt) {
      onChange({ ...output, path: p + expectedExt });
    }
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
          hint={`local or bucket path where the result is written; expected extension ${expectedExt}. Backend rejects on save if the extension disagrees.`}
        >
          <Input
            value={output.path ?? ""}
            onChange={(e) => onChange({ ...output, path: e.target.value })}
            onBlur={onPathBlur}
            placeholder={`./out/result${expectedExt}`}
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
