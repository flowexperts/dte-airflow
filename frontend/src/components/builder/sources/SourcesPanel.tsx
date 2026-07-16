"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Dropdown, Panel, PanelHead, type DropdownOption } from "@/components/ui";
import {
  createSource,
  updateSource,
  type Source,
} from "@/lib/api";
import { SourceEditor } from "./SourceEditor";
import { emptySource } from "./types";
import { useSchemas } from "../schema-context";

/**
 * Slots are ordered source-id references. The picker shows saved sources
 * from `/api/sources`. "+ New source" opens an inline editor whose Save
 * button POSTs to /api/sources then appends the id to the slots list.
 * Editing a saved slot updates the shared record.
 */
export function SourcesPanel({
  sources,
  onChange,
}: {
  sources: string[];
  onChange: (next: string[]) => void;
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

  const setSlot = (i: number, id: string) => {
    if (i >= sources.length) {
      onChange([...sources, id]);
      return;
    }
    const copy = [...sources];
    copy[i] = id;
    onChange(copy);
  };
  const remove = (i: number) => onChange(sources.filter((_, j) => j !== i));

  const openNewAtSlot = (slot: number) => {
    const nextId = `source_${slot + 1}`;
    setEditing({ slot, draft: emptySource(nextId), isNew: true });
    setErr(null);
  };
  const openEdit = async (slot: number) => {
    const id = sources[slot];
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
        await createSource(editing.draft);
        const copy = [...sources];
        copy[editing.slot] = editing.draft.id;
        onChange(copy);
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
      {[...sources, ""].map((id, i) => {
        const isTrailing = i === sources.length;
        const info = available.find((s) => s.id === id);
        const opts: DropdownOption<string>[] = [
          { kind: "action", label: "+ Create new source…", onSelect: () => openNewAtSlot(i) },
          ...(available.length > 0 ? ([{ kind: "divider" }] as DropdownOption<string>[]) : []),
          ...available.map<DropdownOption<string>>((s) => {
            const cfg = (s.config ?? {}) as Record<string, string>;
            const meta = cfg.bucket_url ?? cfg.connection_url ?? s.source_type;
            return { value: s.id, label: s.id, meta };
          }),
          ...(id && !info
            ? ([{ value: id, label: `${id} (missing)`, disabled: true }] as DropdownOption<string>[])
            : []),
        ];
        return (
          <div
            key={`${id}-${i}`}
            className="p-3 border-b border-border last:border-b-0"
          >
            <div className="flex items-center gap-2">
              <div className="flex-1">
                <Dropdown<string>
                  value={id}
                  onChange={(v) => setSlot(i, v)}
                  options={opts}
                  placeholder="— pick a source —"
                />
              </div>
              {id && info && (
                <>
                  <button
                    type="button"
                    onClick={() => refreshById(id)}
                    disabled={schemas[id]?.loading}
                    className={`font-mono text-[10.5px] tracking-[0.15em] uppercase disabled:opacity-50 disabled:pointer-events-none ${
                      schemas[id]?.error
                        ? "text-red hover:opacity-80"
                        : "text-accent hover:text-accent-h"
                    }`}
                    title={
                      schemas[id]?.error
                        ? "click to retry"
                        : schemas[id]?.fields.length
                          ? `${schemas[id]!.fields.length} fields inferred`
                          : "run schema inference for this source"
                    }
                  >
                    {schemas[id]?.loading
                      ? "Inferring…"
                      : schemas[id]?.error
                        ? "Retry infer"
                        : schemas[id]?.fields.length
                          ? `Infer schema · ${schemas[id]!.fields.length}`
                          : "Infer schema"}
                  </button>
                  <button
                    type="button"
                    onClick={() => openEdit(i)}
                    className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
                    title="shared with other pipelines"
                  >
                    Edit
                  </button>
                </>
              )}
              {!isTrailing && (
                <button
                  type="button"
                  onClick={() => remove(i)}
                  aria-label="Remove source"
                  className="text-subtle hover:text-red text-[16px] leading-none px-1"
                >
                  ×
                </button>
              )}
            </div>
            {id && info && schemas[id]?.error && (
              <div className="mt-2 font-mono text-[11.5px] text-red break-all whitespace-pre-wrap">
                {schemas[id]!.error}
              </div>
            )}
          </div>
        );
      })}

      {editing && (
        <div className="border-t-2 border-accent bg-code-bg">
          <div className="px-4 py-2 flex items-center justify-between">
            <span className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-accent">
              {editing.isNew ? "New source" : `Editing ${editing.draft.id}`}
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

    </Panel>
  );
}
