"use client";

import { Field, Input } from "@/components/ui";

interface Config {
  table?: string;
  schema?: string;
  [k: string]: unknown;
}

export function SqlSourceEditor({
  config,
  onChange,
}: {
  config: Config;
  onChange: (next: Config) => void;
}) {
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Schema" hint="optional; defaults per dialect">
          <Input
            value={config.schema ?? ""}
            onChange={(e) => onChange({ ...config, schema: e.target.value })}
            placeholder="public"
          />
        </Field>
        <Field label="Table">
          <Input
            value={config.table ?? ""}
            onChange={(e) => onChange({ ...config, table: e.target.value })}
            placeholder="orders"
          />
        </Field>
      </div>
    </div>
  );
}
