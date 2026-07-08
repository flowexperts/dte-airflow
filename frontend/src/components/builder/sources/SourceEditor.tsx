"use client";

import { Field, Input, Segmented } from "@/components/ui";
import type { DltSource } from "@/lib/api";
import { SOURCE_KINDS, type SourceKind } from "./types";
import { FilesystemSourceEditor } from "./FilesystemSourceEditor";
import { SqlSourceEditor } from "./SqlSourceEditor";
import { MongoSourceEditor } from "./MongoSourceEditor";

const CONFIG_TEMPLATES: Record<SourceKind, Record<string, unknown>> = {
  filesystem:   { bucket_url: "", file_glob: "*.json" },
  sql_database: { connection_string: "", table: "" },
  mongodb:      { connection_url: "", database: "", collection: "" },
};

export function SourceEditor({
  source,
  onChange,
  onRemove,
}: {
  source: DltSource;
  onChange: (next: DltSource) => void;
  onRemove?: () => void;
}) {
  const kind = (source.source_type as SourceKind) ?? "filesystem";
  const config = (source.config ?? {}) as Record<string, unknown>;

  const setKind = (k: SourceKind) => {
    onChange({
      ...source,
      source_type: k,
      config: CONFIG_TEMPLATES[k],
    });
  };

  const setConfig = (next: Record<string, unknown>) => {
    onChange({ ...source, config: next });
  };

  return (
    <div className="p-4 border-b border-border last:border-b-0 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <Segmented<SourceKind>
          value={kind}
          onChange={setKind}
          options={SOURCE_KINDS}
        />
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-red transition-colors"
          >
            Remove
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Source id" hint="referenced by steps">
          <Input
            value={source.id}
            onChange={(e) => onChange({ ...source, id: e.target.value })}
            placeholder="orders"
          />
        </Field>
        <Field label="Load into (table)">
          <Input
            value={source.table ?? ""}
            onChange={(e) => onChange({ ...source, table: e.target.value })}
            placeholder="orders"
          />
        </Field>
      </div>

      {kind === "filesystem" && (
        <FilesystemSourceEditor config={config} onChange={setConfig} />
      )}
      {kind === "sql_database" && (
        <SqlSourceEditor config={config} onChange={setConfig} />
      )}
      {kind === "mongodb" && (
        <MongoSourceEditor config={config} onChange={setConfig} />
      )}
    </div>
  );
}
