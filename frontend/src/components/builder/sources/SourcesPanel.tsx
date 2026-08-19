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

interface Group {
  sourceId: string;
  indices: number[];
}

/** Groups refs by `source_id`, in order of first appearance. A `sql_database`
 *  source is database-scoped (plan 056) — one source can back several table
 *  refs, and this is what lets the panel offer "+ Add table" on the group
 *  instead of sending the user back through the full source picker every
 *  time they want another table off the same connection. */
function groupBySource(sources: SourceTableRef[]): Group[] {
  const order: string[] = [];
  const byId = new Map<string, number[]>();
  sources.forEach((ref, i) => {
    if (!ref.source_id) return;
    if (!byId.has(ref.source_id)) {
      byId.set(ref.source_id, []);
      order.push(ref.source_id);
    }
    byId.get(ref.source_id)!.push(i);
  });
  return order.map((sourceId) => ({ sourceId, indices: byId.get(sourceId)! }));
}

/**
 * Refs are `{source_id, table, alias}` (plan 056), grouped here by source so
 * a database source reads as one card with N table rows rather than N
 * separate "pick a source" slots. `alias` is the compiler's join-registry
 * key; it is never defaulted server-side, so this panel fills it in the
 * moment there's a table (or, for non-DB sources, a source) to name it
 * after.
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
  const [editing, setEditing] = useState<{
    slot: number;
    draft: Source;
    isNew: boolean;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const allAliasesExcept = (skip: Set<number>) =>
    new Set(
      sources
        .map((r, j) => (skip.has(j) ? null : r.alias))
        .filter((a): a is string => Boolean(a)),
    );

  const setRef = (i: number, ref: SourceTableRef) => {
    if (i >= sources.length) {
      onChange([...sources, ref]);
      return;
    }
    const copy = [...sources];
    copy[i] = ref;
    onChange(copy);
  };

  const pickSourceForNewGroup = (sourceId: string) => {
    const info = available.find((s) => s.id === sourceId);
    const isDb = info?.source_type === "sql_database";
    const taken = allAliasesExcept(new Set());
    const alias = isDb ? "" : suggestAlias(info?.name ?? sourceId, taken);
    onChange([...sources, { source_id: sourceId, table: null, alias }]);
  };

  const addTableToGroup = (sourceId: string) => {
    // Alias is filled in once a table is picked (pickTable), same as any
    // fresh slot — left blank here since there's no table name to base it on.
    onChange([...sources, { source_id: sourceId, table: null, alias: "" }]);
  };

  const pickTable = (i: number, table: string) => {
    const ref = sources[i];
    if (!ref) return;
    const taken = allAliasesExcept(new Set([i]));
    const alias = ref.alias ? ref.alias : suggestAlias(table, taken);
    setRef(i, { ...ref, table, alias });
  };

  const setAlias = (i: number, alias: string) => {
    const ref = sources[i];
    if (!ref) return;
    setRef(i, { ...ref, alias });
  };

  const changeRowSource = (i: number, sourceId: string) => {
    const info = available.find((s) => s.id === sourceId);
    const isDb = info?.source_type === "sql_database";
    const taken = allAliasesExcept(new Set([i]));
    const alias = isDb ? "" : suggestAlias(info?.name ?? sourceId, taken);
    setRef(i, { source_id: sourceId, table: null, alias });
  };

  const remove = (i: number) => onChange(sources.filter((_, j) => j !== i));
  const removeGroup = (indices: number[]) => {
    const drop = new Set(indices);
    onChange(sources.filter((_, j) => !drop.has(j)));
  };

  const openNewAtSlot = (slot: number) => {
    const suggestedName = `source_${sources.length + 1}`;
    setEditing({ slot, draft: emptySource(suggestedName), isNew: true });
    setErr(null);
  };
  const openEdit = async (slot: number, sourceId: string) => {
    const existing = available.find((s) => s.id === sourceId);
    if (!existing) {
      setErr(`Source '${sourceId}' not found on server.`);
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
        pickSourceForNewGroup(created.id);
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

  const groups = groupBySource(sources);
  const usedSourceIds = new Set(groups.map((g) => g.sourceId));

  const newSourceOpts: DropdownOption<string>[] = [
    { kind: "action", label: "+ Create new source…", onSelect: () => openNewAtSlot(sources.length) },
    ...(available.length > 0 ? ([{ kind: "divider" }] as DropdownOption<string>[]) : []),
    ...available
      .filter((s) => !usedSourceIds.has(s.id))
      .map<DropdownOption<string>>((s) => {
        const cfg = (s.config ?? {}) as Record<string, string>;
        const meta = cfg.bucket_url ?? cfg.connection_string ?? s.source_type;
        return { value: s.id, label: s.name ?? s.id, meta };
      }),
  ];

  return (
    <Panel>
      <PanelHead label="Sources" count={sources.length} />

      {groups.map((group) => {
        const info = available.find((s) => s.id === group.sourceId);
        const isDb = info?.source_type === "sql_database";
        return (
          <SourceGroup
            key={group.sourceId}
            sourceId={group.sourceId}
            info={info}
            isDb={isDb}
            refs={group.indices.map((i) => ({ index: i, ref: sources[i]! }))}
            aliasIsDuplicate={(i, alias) => !!alias && allAliasesExcept(new Set([i])).has(alias)}
            onChangeRowSource={(i, sourceId) => changeRowSource(i, sourceId)}
            sourceOpts={[
              { kind: "action", label: "+ Create new source…", onSelect: () => openNewAtSlot(group.indices[0]!) },
              ...(available.length > 0 ? ([{ kind: "divider" }] as DropdownOption<string>[]) : []),
              ...available.map<DropdownOption<string>>((s) => ({
                value: s.id,
                label: s.name ?? s.id,
                meta: s.source_type,
              })),
            ]}
            onPickTable={(i, t) => pickTable(i, t)}
            onAliasChange={(i, a) => setAlias(i, a)}
            onEdit={() => openEdit(group.indices[0]!, group.sourceId)}
            onRemoveRow={(i) => remove(i)}
            onRemoveGroup={() => removeGroup(group.indices)}
            onAddTable={isDb ? () => addTableToGroup(group.sourceId) : undefined}
          />
        );
      })}

      <div className="p-3">
        <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-subtle mb-1">
          Add a source
        </div>
        <Dropdown<string>
          value=""
          onChange={(v) => pickSourceForNewGroup(v)}
          options={newSourceOpts}
          placeholder="— pick a source —"
        />
      </div>

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

function SourceGroup({
  sourceId,
  info,
  isDb,
  refs,
  aliasIsDuplicate,
  onChangeRowSource,
  sourceOpts,
  onPickTable,
  onAliasChange,
  onEdit,
  onRemoveRow,
  onRemoveGroup,
  onAddTable,
}: {
  sourceId: string;
  info: Source | undefined;
  isDb: boolean;
  refs: { index: number; ref: SourceTableRef }[];
  aliasIsDuplicate: (index: number, alias: string) => boolean;
  onChangeRowSource: (index: number, sourceId: string) => void;
  sourceOpts: DropdownOption<string>[];
  onPickTable: (index: number, table: string) => void;
  onAliasChange: (index: number, alias: string) => void;
  onEdit: () => void;
  onRemoveRow: (index: number) => void;
  onRemoveGroup: () => void;
  onAddTable?: (() => void) | undefined;
}) {
  const { schemas, refreshById } = useSchemas();

  const { data: tablesData, isLoading: tablesLoading, error: tablesError } = useSWR<{
    tables: string[];
  }>(isDb && info ? `/api/sources/${encodeURIComponent(info.id)}/tables` : null, () =>
    listSourceTables(info!.id),
  );
  const tableOpts: DropdownOption<string>[] = (tablesData?.tables ?? []).map((t) => ({
    value: t,
    label: t,
  }));

  return (
    <div className="border-b border-border last:border-b-0">
      <div className="p-3 pb-2 flex items-center gap-2">
        <div className="flex-1">
          <Dropdown<string>
            value={sourceId}
            onChange={(v) => onChangeRowSource(refs[0]!.index, v)}
            options={sourceOpts}
            placeholder="— pick a source —"
          />
        </div>
        {info && (
          <button
            type="button"
            onClick={onEdit}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
            title="shared with other pipelines"
          >
            Edit
          </button>
        )}
        <button
          type="button"
          onClick={onRemoveGroup}
          aria-label="Remove source"
          className="text-subtle hover:text-red text-[16px] leading-none px-1"
        >
          ×
        </button>
      </div>

      {info &&
        refs.map(({ index, ref }) => {
          const canInfer = Boolean(ref.source_id && ref.alias && (!isDb || ref.table));
          const schemaEntry = ref.alias ? schemas[ref.alias] : undefined;
          return (
            <div key={`${index}-${ref.table ?? ""}`} className="px-3 pb-2 pl-6">
              <div className="grid grid-cols-2 gap-2 items-end">
                {isDb ? (
                  <div>
                    <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-subtle mb-1">
                      Table
                    </div>
                    <Dropdown<string>
                      value={ref.table ?? ""}
                      onChange={(t) => onPickTable(index, t)}
                      options={tableOpts}
                      placeholder={tablesLoading ? "Loading tables…" : "— pick a table —"}
                    />
                  </div>
                ) : (
                  <div />
                )}
                <div className="flex items-center gap-2">
                  <div className="flex-1">
                    <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-subtle mb-1">
                      Alias
                    </div>
                    <input
                      value={ref.alias}
                      onChange={(e) => onAliasChange(index, e.target.value)}
                      placeholder="orders"
                      className="w-full bg-bg text-text border border-border rounded-[var(--radius)] px-2.5 py-1.5 text-[13.5px] font-mono focus:outline-none focus:border-accent"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => refreshById(ref.source_id, ref.alias, ref.table)}
                    disabled={!canInfer || schemaEntry?.loading}
                    className={`font-mono text-[10.5px] tracking-[0.15em] uppercase disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap ${
                      schemaEntry?.error
                        ? "text-red hover:opacity-80"
                        : "text-accent hover:text-accent-h"
                    }`}
                    title={
                      schemaEntry?.error
                        ? "click to retry"
                        : schemaEntry?.fields.length
                          ? `${schemaEntry.fields.length} fields inferred`
                          : "run schema inference for this table"
                    }
                  >
                    {schemaEntry?.loading
                      ? "Inferring…"
                      : schemaEntry?.error
                        ? "Retry infer"
                        : schemaEntry?.fields.length
                          ? `Infer · ${schemaEntry.fields.length}`
                          : "Infer schema"}
                  </button>
                  {refs.length > 1 && (
                    <button
                      type="button"
                      onClick={() => onRemoveRow(index)}
                      aria-label="Remove table"
                      className="text-subtle hover:text-red text-[16px] leading-none px-1"
                    >
                      ×
                    </button>
                  )}
                </div>
              </div>
              {aliasIsDuplicate(index, ref.alias) && (
                <div className="mt-1 font-mono text-[11.5px] text-red">
                  Alias already used by another source in this pipeline.
                </div>
              )}
              {isDb && !ref.table && (
                <div className="mt-1 font-mono text-[11.5px] text-subtle">
                  Pick a table — required for a database source.
                </div>
              )}
              {schemaEntry?.error && (
                <div className="mt-1 font-mono text-[11.5px] text-red break-all whitespace-pre-wrap">
                  {schemaEntry.error}
                </div>
              )}
            </div>
          );
        })}

      {isDb && tablesError && (
        <div className="px-3 pb-2 pl-6 font-mono text-[11px] text-red">
          Couldn&apos;t list tables — {tablesError instanceof Error ? tablesError.message : String(tablesError)}
        </div>
      )}

      {onAddTable && (
        <div className="px-3 pb-3 pl-6">
          <button
            type="button"
            onClick={onAddTable}
            className="font-mono text-[11.5px] text-accent hover:text-accent-h"
          >
            + Add table from {info?.name ?? sourceId}
          </button>
        </div>
      )}
    </div>
  );
}
