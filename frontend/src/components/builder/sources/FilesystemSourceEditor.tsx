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
        label="File glob"
        hint="pattern (or exact filename) relative to the bucket / directory"
      >
        <Input
          value={config.file_glob ?? ""}
          onChange={(e) => onChange({ ...config, file_glob: e.target.value })}
          placeholder="*.json  or  orders.json"
        />
      </Field>
    </div>
  );
}
