"use client";

import { Dropdown, Field, Input } from "@/components/ui";
import type { Source } from "@/lib/api";
import { SOURCE_KINDS, SOURCE_CONNECTION_COMPAT, type SourceKind } from "./types";
import { FilesystemSourceEditor } from "./FilesystemSourceEditor";
import { SqlSourceEditor } from "./SqlSourceEditor";
import { MongoSourceEditor } from "./MongoSourceEditor";
import { useSchemasOptional } from "../schema-context";
import { ConnectionPicker } from "../ConnectionPicker";

const CONFIG_TEMPLATES: Record<SourceKind, Record<string, unknown>> = {
  filesystem:   { bucket_url: "", file_glob: "*.json" },
  s3:           { bucket_url: "", file_glob: "*.json" },
  gcs:          { bucket_url: "", file_glob: "*.json" },
  azure:        { bucket_url: "", file_glob: "*.json" },
  sql_database: { table: "" },
  mongodb:      { database: "", collection: "" },
  rest_api:     { client: {}, resources: [] },
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
      // Wrong connection type when switching kind; clear so user reselects.
      connection_id: SOURCE_CONNECTION_COMPAT[k].includes(
        (source as { connection_type?: string })?.connection_type as never,
      )
        ? source.connection_id
        : "",
    });
  };

  const setConfig = (next: Record<string, unknown>) => {
    onChange({ ...source, config: next });
  };

  const schemaCtx = useSchemasOptional();
  const entry = schemaCtx?.schemas[source.id];

  return (
    <div className="p-4 border-b border-border last:border-b-0 space-y-3">
      {onRemove && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onRemove}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-red transition-colors"
          >
            Remove
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Field label="Source id" hint="referenced by steps; also used as the local table name">
          <Input
            value={source.id}
            onChange={(e) => {
              const id = e.target.value;
              onChange({ ...source, id, table: id });
            }}
            placeholder="orders"
          />
        </Field>
        <Field label="Type">
          <Dropdown<SourceKind>
            value={kind}
            onChange={setKind}
            options={SOURCE_KINDS}
          />
        </Field>
      </div>

      <ConnectionPicker
        value={source.connection_id}
        onChange={(id) => onChange({ ...source, connection_id: id })}
        allowedTypes={SOURCE_CONNECTION_COMPAT[kind]}
      />

      {(kind === "filesystem" || kind === "s3" || kind === "gcs" || kind === "azure") && (
        <FilesystemSourceEditor
          config={config}
          onChange={setConfig}
          format={source.format ?? null}
          onFormatChange={(fmt) => onChange({ ...source, format: fmt })}
        />
      )}
      {kind === "sql_database" && (
        <SqlSourceEditor config={config} onChange={setConfig} />
      )}
      {kind === "mongodb" && (
        <MongoSourceEditor config={config} onChange={setConfig} />
      )}
      {kind === "rest_api" && (
        <div className="p-3 border border-border rounded bg-code-bg text-xs text-subtle font-mono">
          rest_api uses a raw dlt config dict; edit `sources/{"{"}source.id{"}"}` directly for now.
        </div>
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
            disabled={!source.id || !source.connection_id || entry?.loading}
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
