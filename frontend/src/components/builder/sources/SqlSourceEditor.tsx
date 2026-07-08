"use client";

import { Field, Input, Textarea } from "@/components/ui";

interface Config {
  connection_string?: string;
  table?: string;
  query?: string;
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
      <Field
        label="Connection string"
        hint="e.g. postgresql://user:pass@host:5432/db (or use env-var interpolation)"
      >
        <Input
          value={config.connection_string ?? ""}
          onChange={(e) =>
            onChange({ ...config, connection_string: e.target.value })
          }
          placeholder="postgresql://user@host/db"
        />
      </Field>
      <Field label="Table" hint="omit if using a query below">
        <Input
          value={config.table ?? ""}
          onChange={(e) => onChange({ ...config, table: e.target.value })}
          placeholder="public.orders"
        />
      </Field>
      <Field label="Query (optional)" hint="overrides table when set">
        <Textarea
          value={config.query ?? ""}
          onChange={(e) => onChange({ ...config, query: e.target.value })}
          placeholder="SELECT * FROM orders WHERE created_at &gt; :cutoff"
          rows={3}
        />
      </Field>
    </div>
  );
}
