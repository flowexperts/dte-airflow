"use client";

import { Panel, PanelHead } from "@/components/ui";
import type { DltSource } from "@/lib/api";
import { SourceEditor } from "./SourceEditor";
import { emptySource } from "./types";

export function SourcesPanel({
  sources,
  onChange,
}: {
  sources: DltSource[];
  onChange: (next: DltSource[]) => void;
}) {
  const update = (i: number, next: DltSource) => {
    const copy = [...sources];
    copy[i] = next;
    onChange(copy);
  };
  const remove = (i: number) => {
    onChange(sources.filter((_, j) => j !== i));
  };
  const add = () => {
    const nextId = `source_${sources.length + 1}`;
    onChange([...sources, emptySource(nextId)]);
  };

  return (
    <Panel>
      <PanelHead label="Sources" count={sources.length} />
      {sources.length === 0 ? (
        <div className="p-6 text-center text-sm text-subtle">
          No sources yet.
        </div>
      ) : (
        sources.map((s, i) => (
          <SourceEditor
            key={i}
            source={s}
            onChange={(next) => update(i, next)}
            onRemove={() => remove(i)}
          />
        ))
      )}
      <button
        type="button"
        onClick={add}
        className="w-full text-center py-3 px-3.5 border-t border-dashed border-border font-medium text-xs text-subtle hover:text-accent hover:bg-[color:var(--accent-tint)] transition-colors"
      >
        <span className="text-accent font-bold mr-1">+</span> Add source
      </button>
    </Panel>
  );
}
