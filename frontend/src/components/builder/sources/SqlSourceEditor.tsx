"use client";

import useSWR from "swr";
import { Dropdown, Field, type DropdownOption } from "@/components/ui";

interface Config {
  schema?: string;
  [k: string]: unknown;
}

/**
 * `sql_database` sources are database-scoped, not table-scoped (plan 056) —
 * which table is read is a per-pipeline decision (`SourceTableRef.table`),
 * picked on `SourcesPanel`. This editor only carries the schema/database
 * name, offered as a dropdown once a connection is picked so it isn't typed
 * blind.
 */
export function SqlSourceEditor({
  config,
  onChange,
  connectionId,
}: {
  config: Config;
  onChange: (next: Config) => void;
  connectionId?: string;
}) {
  const { data, isLoading, error } = useSWR<{ schemas: string[] }>(
    connectionId ? `/api/connections/${encodeURIComponent(connectionId)}/schemas` : null,
  );
  const schemas = data?.schemas ?? [];

  const opts: DropdownOption<string>[] = [
    ...schemas.map<DropdownOption<string>>((s) => ({ value: s, label: s })),
    ...(config.schema && !schemas.includes(config.schema)
      ? ([{ value: config.schema, label: `${config.schema} (custom)` }] as DropdownOption<string>[])
      : []),
  ];

  return (
    <div className="grid gap-3">
      <Field
        label="Schema"
        hint={
          !connectionId
            ? "pick a connection first"
            : error
              ? "couldn't list schemas — type one manually below"
              : "optional; defaults per dialect"
        }
      >
        <Dropdown<string>
          value={config.schema ?? ""}
          onChange={(v) => onChange({ ...config, schema: v })}
          options={opts}
          placeholder={isLoading ? "Loading schemas…" : "public"}
          disabled={!connectionId}
        />
      </Field>
    </div>
  );
}
