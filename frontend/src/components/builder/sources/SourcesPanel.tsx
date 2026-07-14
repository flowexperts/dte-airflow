"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Panel, PanelHead } from "@/components/ui";
import {
  createSource,
  updateSource,
  type Source,
} from "@/lib/api";
import { SourceEditor } from "./SourceEditor";
import { emptySource } from "./types";

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
  const [editing, setEditing] = useState<{
    slot: number;
    draft: Source;
    isNew: boolean;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const setSlot = (i: number, id: string) => {
    const copy = [...sources];
    copy[i] = id;
    onChange(copy);
  };
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= sources.length) return;
    const copy = [...sources];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    onChange(copy);
  };
  const remove = (i: number) => onChange(sources.filter((_, j) => j !== i));

  const openNew = () => {
    const nextId = `source_${sources.length + 1}`;
    setEditing({ slot: sources.length, draft: emptySource(nextId), isNew: true });
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
      {sources.length === 0 && !editing && (
        <div className="p-6 text-center text-sm text-subtle">
          No sources yet.
        </div>
      )}
      {sources.map((id, i) => {
        const info = available.find((s) => s.id === id);
        return (
          <div
            key={`${id}-${i}`}
            className="flex items-center gap-2 p-3 border-b border-border last:border-b-0"
          >
            <span className="font-mono text-[10.5px] text-subtle w-6">
              {String(i + 1).padStart(2, "0")}
            </span>
            <select
              className="flex-1 bg-transparent border border-border rounded px-2 py-1 font-mono text-[12px]"
              value={id}
              onChange={(e) => setSlot(i, e.target.value)}
            >
              <option value="" disabled>
                — pick a source —
              </option>
              {available.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.id} · {s.source_type}
                  {s.config &&
                    ((s.config as Record<string, string>).bucket_url ||
                      (s.config as Record<string, string>).connection_url ||
                      "")
                    ? ` · ${
                        (s.config as Record<string, string>).bucket_url ??
                        (s.config as Record<string, string>).connection_url ??
                        ""
                      }`
                    : ""}
                </option>
              ))}
              {id && !info && <option value={id}>{id} (missing)</option>}
            </select>
            <button
              type="button"
              onClick={() => openEdit(i)}
              className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
              title="shared with other pipelines"
            >
              Edit
            </button>
            <button
              type="button"
              onClick={() => move(i, -1)}
              disabled={i === 0}
              className="font-mono text-[12px] px-1 text-subtle disabled:opacity-30"
            >
              ↑
            </button>
            <button
              type="button"
              onClick={() => move(i, 1)}
              disabled={i === sources.length - 1}
              className="font-mono text-[12px] px-1 text-subtle disabled:opacity-30"
            >
              ↓
            </button>
            <button
              type="button"
              onClick={() => remove(i)}
              className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-red"
            >
              Remove
            </button>
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

      {!editing && (
        <button
          type="button"
          onClick={openNew}
          className="w-full text-center py-3 px-3.5 border-t border-dashed border-border font-medium text-xs text-subtle hover:text-accent hover:bg-[color:var(--accent-tint)] transition-colors"
        >
          <span className="text-accent font-bold mr-1">+</span> Add source
        </button>
      )}
    </Panel>
  );
}
