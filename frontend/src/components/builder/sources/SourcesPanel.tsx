"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Dropdown, Panel, PanelHead, type DropdownOption } from "@/components/ui";
import {
  createSource,
  listSourceTables,
  updateSource,
  type Source,
  type SourceTableRef,
} from "@/lib/api";
import { SourceEditor } from "./SourceEditor";
import { emptySource } from "./types";
import { useSchemas } from "../schema-context";

const emptySlot = (): SourceTableRef => ({ source_id: "", table: null, alias: "" });

/** Turns a table/source name into something that satisfies the backend's
 *  alias regex (`^[A-Za-z_][A-Za-z0-9_]*$`), then dedupes it against the
 *  aliases already in use — `orders`, `orders_2` on collision. */
function suggestAlias(base: string, taken: Set<string>): string {
  let candidate = base.replace(/[^A-Za-z0-9_]/g, "_");
  if (!candidate || /^[0-9]/.test(candidate)) candidate = `_${candidate}`;
  if (!taken.has(candidate)) return candidate;
  let n = 2;
  while (taken.has(`${candidate}_${n}`)) n++;
  return `${candidate}_${n}`;
}

/**
 * Slots are ordered `SourceTableRef`s: `{source_id, table, alias}` (plan
 * 056). A `sql_database` Source is database-scoped — the table read is a
 * per-slot decision, offered as a dropdown fed by `GET
 * /api/sources/{id}/tables` once a source is picked. `alias` is the
 * compiler's join-registry key; it is never defaulted server-side, so this
 * panel fills it in the moment there's a table (or, for non-DB sources, a
 * source) to name it after.
 */
export function SourcesPanel({
  sources,
  onChange,
  error,
}: {
  sources: SourceTableRef[];
  onChange: (next: SourceTableRef[]) => void;
  /** Validation error to display beneath the panel. */
  error?: string | undefined;
}) {
  const { data: available = [], mutate } = useSWR<Source[]>("/api/sources");
  const { schemas, refreshById } = useSchemas();
  const [editing, setEditing] = useState<{
    slot: number;
    draft: Source;
    isNew: boolean;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const aliasesExcept = (i: number) =>
    new Set(sources.filter((_, j) => j !== i).map((r) => r.alias).filter(Boolean));

  const setSlot = (i: number, ref: SourceTableRef) => {
    if (i >= sources.length) {
      onChange([...sources, ref]);
      return;
    }
    const copy = [...sources];
    copy[i] = ref;
    onChange(copy);
  };

  const pickSource = (i: number, sourceId: string) => {
    const info = available.find((s) => s.id === sourceId);
    const isDb = info?.source_type === "sql_database";
    const taken = aliasesExcept(i);
    const alias = isDb ? "" : suggestAlias(info?.name ?? sourceId, taken);
    setSlot(i, { source_id: sourceId, table: null, alias });
  };

  const pickTable = (i: number, table: string) => {
    const ref = sources[i];
    if (!ref) return;
    const taken = aliasesExcept(i);
    const alias = ref.alias ? ref.alias : suggestAlias(table, taken);
    setSlot(i, { ...ref, table, alias });
  };

  const setAlias = (i: number, alias: string) => {
    const ref = sources[i];
    if (!ref) return;
    setSlot(i, { ...ref, alias });
  };

  const remove = (i: number) => onChange(sources.filter((_, j) => j !== i));

  const openNewAtSlot = (slot: number) => {
    const suggestedName = `source_${slot + 1}`;
    setEditing({ slot, draft: emptySource(suggestedName), isNew: true });
    setErr(null);
  };
  const openEdit = async (slot: number) => {
    const id = sources[slot]?.source_id;
    const existing = available.find((s) => s.id === id);
    if (!existing) {
      setErr(`Source '${id}' not found on server.`);
      return;
    }
    setEditing({ slot, draft: existing, isNew: false });
    setErr(null);
  };

  const saveDraft = async () => {
    if (!editing) return;
    setBusy(true);
    setErr(null);
    try {
      if (editing.isNew) {
        // Server generates the id — use the response, not the draft.
        const created = await createSource(editing.draft);
        pickSource(editing.slot, created.id);
      } else {
        await updateSource(editing.draft.id, editing.draft);
      }
      await mutate();
      setEditing(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel>
      <PanelHead label="Sources" count={sources.length} />
      {[...sources, emptySlot()].map((ref, i) => {
        const isTrailing = i === sources.length;
        const info = available.find((s) => s.id === ref.source_id);
        const isDb = info?.source_type === "sql_database";
        const schemaKey = ref.alias;
        const opts: DropdownOption<string>[] = [
          { kind: "action", label: "+ Create new source…", onSelect: () => openNewAtSlot(i) },
          ...(available.length > 0 ? ([{ kind: "divider" }] as DropdownOption<string>[]) : []),
          ...available.map<DropdownOption<string>>((s) => {
            const cfg = (s.config ?? {}) as Record<string, string>;
            const meta = cfg.bucket_url ?? cfg.connection_string ?? s.source_type;
            return { value: s.id, label: s.name ?? s.id, meta };
          }),
          ...(ref.source_id && !info
            ? ([{ value: ref.source_id, label: `${ref.source_id} (missing)`, disabled: true }] as DropdownOption<string>[])
            : []),
        ];
        return (
          <SourceSlot
            key={`${ref.source_id}-${ref.table ?? ""}-${i}`}
            tableRef={ref}
            info={info}
            isDb={isDb}
            opts={opts}
            aliasDuplicate={!!ref.alias && aliasesExcept(i).has(ref.alias)}
            schemaEntry={schemaKey ? schemas[schemaKey] : undefined}
            onPickSource={(v) => pickSource(i, v)}
            onPickTable={(t) => pickTable(i, t)}
            onAliasChange={(a) => setAlias(i, a)}
            onInfer={() =>
              ref.source_id && ref.alias && refreshById(ref.source_id, ref.alias, ref.table)
            }
            onEdit={() => openEdit(i)}
            onRemove={!isTrailing ? () => remove(i) : undefined}
          />
        );
      })}

      {editing && (
        <div className="border-t-2 border-accent bg-code-bg">
          <div className="px-4 py-2 flex items-center justify-between">
            <span className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-accent">
              {editing.isNew ? "New source" : `Editing ${editing.draft.name ?? editing.draft.id}`}
              {!editing.isNew && (
                <span className="ml-2 text-subtle normal-case tracking-normal">
                  · shared with other pipelines
                </span>
              )}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditing(null)}
                disabled={busy}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={saveDraft}
                disabled={busy}
              >
                {busy ? "Saving…" : "Save source"}
              </Button>
            </div>
          </div>
          {err && (
            <div className="px-4 pb-2 font-mono text-[11.5px] text-red">
              {err}
            </div>
          )}
          <SourceEditor
            source={editing.draft}
            onChange={(next) =>
              setEditing((e) => (e ? { ...e, draft: next } : null))
            }
          />
        </div>
      )}

      {error && (
        <div className="px-3 pb-2 font-mono text-[11.5px] text-red">{error}</div>
      )}
    </Panel>
  );
}

function SourceSlot({
  tableRef,
  info,
  isDb,
  opts,
  aliasDuplicate,
  schemaEntry,
  onPickSource,
  onPickTable,
  onAliasChange,
  onInfer,
  onEdit,
  onRemove,
}: {
  tableRef: SourceTableRef;
  info: Source | undefined;
  isDb: boolean;
  opts: DropdownOption<string>[];
  aliasDuplicate: boolean;
  schemaEntry: { fields: unknown[]; loading: boolean; error: string | null } | undefined;
  onPickSource: (id: string) => void;
  onPickTable: (table: string) => void;
  onAliasChange: (alias: string) => void;
  onInfer: () => void;
  onEdit: () => void;
  onRemove?: (() => void) | undefined;
}) {
  // Only fetch tables once a sql_database source is actually picked.
  const { data: tablesData, isLoading: tablesLoading, error: tablesError } = useSWR<{
    tables: string[];
  }>(isDb && info ? `/api/sources/${encodeURIComponent(info.id)}/tables` : null, () =>
    listSourceTables(info!.id),
  );
  const tableOpts: DropdownOption<string>[] = (tablesData?.tables ?? []).map((t) => ({
    value: t,
    label: t,
  }));
  const canInfer = Boolean(tableRef.source_id && tableRef.alias && (!isDb || tableRef.table));

  return (
    <div className="p-3 border-b border-border last:border-b-0">
      <div className="flex items-center gap-2">
        <div className="flex-1">
          <Dropdown<string>
            value={tableRef.source_id}
            onChange={onPickSource}
            options={opts}
            placeholder="— pick a source —"
          />
        </div>
        {tableRef.source_id && info && (
          <>
            <button
              type="button"
              onClick={onInfer}
              disabled={!canInfer || schemaEntry?.loading}
              className={`font-mono text-[10.5px] tracking-[0.15em] uppercase disabled:opacity-50 disabled:pointer-events-none ${
                schemaEntry?.error
                  ? "text-red hover:opacity-80"
                  : "text-accent hover:text-accent-h"
              }`}
              title={
                schemaEntry?.error
                  ? "click to retry"
                  : schemaEntry?.fields.length
                    ? `${schemaEntry.fields.length} fields inferred`
                    : "run schema inference for this source"
              }
            >
              {schemaEntry?.loading
                ? "Inferring…"
                : schemaEntry?.error
                  ? "Retry infer"
                  : schemaEntry?.fields.length
                    ? `Infer schema · ${schemaEntry.fields.length}`
                    : "Infer schema"}
            </button>
            <button
              type="button"
              onClick={onEdit}
              className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
              title="shared with other pipelines"
            >
              Edit
            </button>
          </>
        )}
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label="Remove source"
            className="text-subtle hover:text-red text-[16px] leading-none px-1"
          >
            ×
          </button>
        )}
      </div>

      {tableRef.source_id && info && isDb && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <div>
            <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-subtle mb-1">
              Table
            </div>
            <Dropdown<string>
              value={tableRef.table ?? ""}
              onChange={onPickTable}
              options={tableOpts}
              placeholder={tablesLoading ? "Loading tables…" : "— pick a table —"}
            />
            {tablesError && (
              <div className="mt-1 font-mono text-[11px] text-red">
                Couldn&apos;t list tables — {tablesError instanceof Error ? tablesError.message : String(tablesError)}
              </div>
            )}
          </div>
          <div>
            <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-subtle mb-1">
              Alias
            </div>
            <input
              value={tableRef.alias}
              onChange={(e) => onAliasChange(e.target.value)}
              placeholder="orders"
              className="w-full bg-bg text-text border border-border rounded-[var(--radius)] px-2.5 py-1.5 text-[13.5px] font-mono focus:outline-none focus:border-accent"
            />
          </div>
        </div>
      )}

      {tableRef.source_id && info && !isDb && (
        <div className="mt-2">
          <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-subtle mb-1">
            Alias
          </div>
          <input
            value={tableRef.alias}
            onChange={(e) => onAliasChange(e.target.value)}
            placeholder="orders"
            className="w-full bg-bg text-text border border-border rounded-[var(--radius)] px-2.5 py-1.5 text-[13.5px] font-mono focus:outline-none focus:border-accent"
          />
        </div>
      )}

      {aliasDuplicate && (
        <div className="mt-2 font-mono text-[11.5px] text-red">
          Alias already used by another source in this pipeline.
        </div>
      )}
      {tableRef.source_id && isDb && !tableRef.table && (
        <div className="mt-2 font-mono text-[11.5px] text-subtle">
          Pick a table — required for a database source.
        </div>
      )}
      {tableRef.source_id && info && schemaEntry?.error && (
        <div className="mt-2 font-mono text-[11.5px] text-red break-all whitespace-pre-wrap">
          {schemaEntry.error}
        </div>
      )}
    </div>
  );
}
