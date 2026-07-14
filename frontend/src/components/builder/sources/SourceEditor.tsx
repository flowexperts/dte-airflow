"use client";

import { Field, Input, Segmented } from "@/components/ui";
import type { Source } from "@/lib/api";
import { SOURCE_KINDS, type SourceKind } from "./types";
import { FilesystemSourceEditor } from "./FilesystemSourceEditor";
import { SqlSourceEditor } from "./SqlSourceEditor";
import { MongoSourceEditor } from "./MongoSourceEditor";
import { useSchemasOptional } from "../schema-context";

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
  source: Source;
  onChange: (next: Source) => void;
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

  const schemaCtx = useSchemasOptional();
  const entry = schemaCtx?.schemas[source.id];

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

      {schemaCtx && (
      <div className="pt-2 border-t border-dashed border-border">
        <div className="flex items-center justify-between mb-2">
          <span className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
            Inferred fields
            {entry?.fields.length ? ` · ${entry.fields.length}` : ""}
          </span>
          <button
            type="button"
            onClick={() => schemaCtx.refresh(source)}
            disabled={!source.id || entry?.loading}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h disabled:opacity-50 disabled:pointer-events-none"
          >
            {entry?.loading ? "Inferring…" : "Infer schema"}
          </button>
        </div>
        {entry?.error && (
          <div className="font-mono text-[11.5px] text-red mb-2">
            {entry.error}
          </div>
        )}
        {entry?.fields.length ? (
          <div className="flex flex-wrap gap-1.5">
            {entry.fields.map((f) => (
              <span
                key={f.name}
                className="font-mono text-[11px] px-1.5 py-0.5 rounded border border-border bg-code-bg"
              >
                <span className="text-text">{f.name}</span>
                <span className="text-subtle ml-1.5">{f.type}</span>
              </span>
            ))}
          </div>
        ) : (
          <div className="font-mono text-[11.5px] text-subtle">
            Click <span className="text-accent">Infer schema</span> after
            filling the config to see available fields (also enables
            autocomplete in step editors).
          </div>
        )}
      </div>
      )}
    </div>
  );
}
