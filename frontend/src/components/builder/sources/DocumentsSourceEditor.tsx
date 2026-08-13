"use client";

import { Field, Input } from "@/components/ui";

interface Config {
  bucket_url?: string;
  file_glob?: string;
  [k: string]: unknown;
}

/** Documents source config.
 *
 * Deliberately not `FilesystemSourceEditor` with a different glob: a documents
 * source has no reader *format*. Listing only stats the files — nothing is
 * parsed until an `extract` step runs — so a format dropdown here would be a
 * control that does nothing. */
export function DocumentsSourceEditor({
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
        hint="must be a DIRECTORY, not a file. e.g. /Users/me/invoices or s3://acme-docs/2024/"
      >
        <Input
          value={config.bucket_url ?? ""}
          onChange={(e) => onChange({ ...config, bucket_url: e.target.value })}
          placeholder="/Users/me/invoices  or  s3://acme-docs/2024/"
        />
      </Field>
      <Field
        label="File glob"
        hint="pattern relative to the directory. `**/` recurses into subdirectories."
      >
        <Input
          value={config.file_glob ?? ""}
          onChange={(e) => onChange({ ...config, file_glob: e.target.value })}
          placeholder="**/*.pdf"
        />
      </Field>
      <p className="font-mono text-[11px] text-subtle">
        Lists documents — path, size, modified time — without opening them.
        Add an <span className="text-accent">Extract</span> step to read their
        text.
      </p>
    </div>
  );
}
