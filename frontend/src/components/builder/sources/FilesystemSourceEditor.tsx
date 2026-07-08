"use client";

import { Field, Input } from "@/components/ui";

interface Config {
  bucket_url?: string;
  file_glob?: string;
  [k: string]: unknown;
}

export function FilesystemSourceEditor({
  config,
  onChange,
}: {
  config: Config;
  onChange: (next: Config) => void;
}) {
  return (
    <div className="grid gap-3">
      <Field
        label="Bucket URL or local path"
        hint="e.g. s3://acme-lake/raw/, gs://…, or /Users/me/data"
      >
        <Input
          value={config.bucket_url ?? ""}
          onChange={(e) => onChange({ ...config, bucket_url: e.target.value })}
          placeholder="s3://acme-lake/raw/"
        />
      </Field>
      <Field label="File glob" hint="pattern relative to the bucket URL">
        <Input
          value={config.file_glob ?? ""}
          onChange={(e) => onChange({ ...config, file_glob: e.target.value })}
          placeholder="*.json"
        />
      </Field>
    </div>
  );
}
