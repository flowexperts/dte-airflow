"use client";

import { Field, Input } from "@/components/ui";

interface Config {
  connection_url?: string;
  database?: string;
  collection?: string;
  [k: string]: unknown;
}

export function MongoSourceEditor({
  config,
  onChange,
}: {
  config: Config;
  onChange: (next: Config) => void;
}) {
  return (
    <div className="grid gap-3">
      <Field label="Connection URL">
        <Input
          value={config.connection_url ?? ""}
          onChange={(e) =>
            onChange({ ...config, connection_url: e.target.value })
          }
          placeholder="mongodb://user:pass@host:27017"
        />
      </Field>
      <Field label="Database">
        <Input
          value={config.database ?? ""}
          onChange={(e) => onChange({ ...config, database: e.target.value })}
          placeholder="app"
        />
      </Field>
      <Field label="Collection">
        <Input
          value={config.collection ?? ""}
          onChange={(e) => onChange({ ...config, collection: e.target.value })}
          placeholder="orders"
        />
      </Field>
    </div>
  );
}
