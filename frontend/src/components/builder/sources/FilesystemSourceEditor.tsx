"use client";

import { Dropdown, Field, Input, type DropdownOption } from "@/components/ui";
import type { FileFormat } from "@/lib/api";

interface Config {
  bucket_url?: string;
  file_glob?: string;
  [k: string]: unknown;
}

const FORMAT_OPTIONS: DropdownOption<FileFormat | "">[] = [
  { value: "", label: "Auto (from extension)", meta: "*.ext → format" },
  { value: "json", label: "JSON", meta: ".json" },
  { value: "jsonl", label: "JSONL / NDJSON", meta: ".jsonl / .ndjson" },
  { value: "csv", label: "CSV / TSV", meta: ".csv / .tsv" },
  { value: "parquet", label: "Parquet", meta: ".parquet" },
  { value: "excel", label: "Excel (.xlsx)", meta: ".xlsx" },
];

const GLOB_PLACEHOLDER: Record<FileFormat, string> = {
  json: "*.json",
  jsonl: "*.jsonl",
  ndjson: "*.ndjson",
  csv: "*.csv",
  parquet: "*.parquet",
  excel: "*.xlsx",
};

export function FilesystemSourceEditor({
  config,
  onChange,
  format,
  onFormatChange,
}: {
  config: Config;
  onChange: (next: Config) => void;
  /** Top-level `Source.format` — lives on the sources row, not inside
   *  `config`, since migration 009. */
  format: FileFormat | null | undefined;
  onFormatChange: (next: FileFormat | null) => void;
}) {
  const current = (format ?? "") as FileFormat | "";
  const placeholder =
    (current && GLOB_PLACEHOLDER[current]) ?? "*.json  or  orders.json";

  return (
    <div className="grid gap-3">
      <Field
        label="Bucket or directory"
        hint="must be a DIRECTORY, not a file. e.g. s3://acme-lake/raw/ or /Users/me/data. To load one specific file, put the directory here and its exact name in File glob."
      >
        <Input
          value={config.bucket_url ?? ""}
          onChange={(e) => onChange({ ...config, bucket_url: e.target.value })}
          placeholder="s3://acme-lake/raw/  or  /Users/me/data"
        />
      </Field>
      <Field
        label="File type"
        hint="'Auto' picks reader by file extension. Override if your files don't match convention (e.g. .txt that's actually CSV). Backend rejects on save if this disagrees with the glob's extension."
      >
        <Dropdown<FileFormat | "">
          value={current}
          onChange={(v) => onFormatChange(v === "" ? null : v)}
          options={FORMAT_OPTIONS}
        />
      </Field>
      <Field
        label="File glob"
        hint="pattern (or exact filename) relative to the bucket / directory"
      >
        <Input
          value={config.file_glob ?? ""}
          onChange={(e) => onChange({ ...config, file_glob: e.target.value })}
          placeholder={placeholder}
        />
      </Field>
    </div>
  );
}
