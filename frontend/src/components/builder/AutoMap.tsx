"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  Button,
  DataTable,
  FieldPicker,
  Panel,
  PanelHead,
  Pill,
  type Column,
} from "@/components/ui";
import { automapFields, getDestinationSchema, type AutomapMatch, type SchemaField } from "@/lib/api";
import { useSchemas } from "./schema-context";
import type { StepShape } from "./steps/types";

/**
 * Propose a source→destination column mapping, then write it as ordinary
 * `rename` + `select` steps.
 *
 * The proposal is never applied on arrival: every row is a checkbox, and a
 * guessed source is editable in place. A mapping the user did not look at
 * is a silently corrupted column, and nothing here can tell the difference
 * between a good guess and a plausible one.
 */

/** Flatten the schema tree to dotted leaves — the wire form for field refs. */
function leaves(fields: SchemaField[], prefix = ""): { name: string; type: string }[] {
  return fields.flatMap((f) => {
    const name = prefix ? `${prefix}.${f.name}` : f.name;
    return f.children?.length
      ? leaves(f.children, name)
      : [{ name, type: f.type }];
  });
}

function confidencePill(m: AutomapMatch) {
  if (!m.source) return <span className="text-subtle text-[11.5px]">no match</span>;
  const pct = `${Math.round(m.confidence * 100)}%`;
  const status = m.confidence >= 0.9 ? "ok" : m.confidence >= 0.7 ? "warn" : "pending";
  return (
    <Pill status={status}>
      {pct} · {m.via}
    </Pill>
  );
}

/** The button and its dialog are one component: the proposal is kicked off
 *  by the click that opens the dialog, so there is no mount effect racing
 *  the first render (and no paid model call fired from one). */
export function AutoMapButton({
  outputId,
  steps,
  onChange,
}: {
  outputId: string;
  steps: StepShape[];
  onChange: (next: StepShape[]) => void;
}) {
  const { fieldsAtStep } = useSchemas();
  const sourceFields = leaves(fieldsAtStep(steps.length));

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [matches, setMatches] = useState<AutomapMatch[]>([]);
  const [accepted, setAccepted] = useState<Set<string>>(new Set());

  const onClose = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  /* Not memoized, and that is deliberate: it is only ever called from the
   * click handler, and a `useCallback` here froze `sourceFields` at the
   * first render — before schema inference had returned — so every row came
   * back unmapped against a destination whose columns had loaded fine. */
  const propose = async () => {
    setLoading(true);
    setError(null);
    setLlmError(null);
    try {
      const dest = await getDestinationSchema(outputId);
      const result = await automapFields({
        source_fields: sourceFields,
        dest_fields: leaves(dest.fields),
        use_llm: true,
      });
      setMatches(result.matches);
      setLlmError(result.llm_error);
      // Only the confident rows start ticked. A type mismatch caps
      // confidence below this line, so it is always an explicit decision.
      setAccepted(
        new Set(result.matches.filter((m) => m.source && m.confidence >= 0.9).map((m) => m.dest)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setMatches([]);
    } finally {
      setLoading(false);
    }
  };

  const setSource = (dest: string, source: string) =>
    setMatches((prev) =>
      prev.map((m) =>
        m.dest === dest ? { ...m, source: source || null, via: null, confidence: 0, warning: null } : m,
      ),
    );

  /* One `select`, not a `rename` + `select`. A select field carries an
   * `alias`, so projecting and renaming are the same step — and the rename
   * op cannot express half of what is offered here anyway: it validates
   * against `table.columns`, so a dotted struct path (`order.amount`, what
   * every filesystem source produces) raises rather than resolving. */
  const apply = () => {
    const picked = matches.filter((m) => m.source && accepted.has(m.dest));
    onChange([
      ...steps,
      {
        op: "select",
        fields: picked.map((m) =>
          m.source === m.dest ? { field: m.dest } : { field: m.source, alias: m.dest },
        ),
      } as StepShape,
    ]);
    onClose();
  };

  const columns: Column<AutomapMatch>[] = [
    {
      key: "dest",
      header: "Destination column",
      width: "1fr",
      render: (m) => <span className="font-mono text-[12px]">{m.dest}</span>,
    },
    {
      key: "source",
      header: "Source column",
      width: "1fr",
      render: (m) => (
        <FieldPicker
          value={m.source ?? ""}
          onChange={(v) => setSource(m.dest, v)}
          options={sourceFields}
          placeholder="unmapped"
          variant="tree"
        />
      ),
    },
    {
      key: "confidence",
      header: "Match",
      width: "150px",
      render: confidencePill,
    },
    {
      key: "warning",
      header: "",
      width: "150px",
      render: (m) =>
        m.warning ? (
          <span className="font-mono text-[11px] text-gold">{m.warning}</span>
        ) : null,
    },
  ];

  const acceptedCount = matches.filter((m) => m.source && accepted.has(m.dest)).length;

  const dialog =
    !open || typeof document === "undefined"
      ? null
      : createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-8"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-[900px] mt-8"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute -top-2 -right-2 z-10 w-6 h-6 rounded-full border border-border bg-surface text-subtle hover:text-red text-[13px] leading-none flex items-center justify-center shadow-sm"
        >
          ×
        </button>
        <Panel>
          <PanelHead
            label="Auto-map fields"
            count={loading ? "Matching…" : `${acceptedCount} of ${matches.length} accepted`}
          />
          {error && (
            <div className="px-3.5 py-3 border-b border-border text-red font-mono text-[12px]">
              {error}
            </div>
          )}
          {llmError && (
            <div className="px-3.5 py-3 border-b border-border text-gold font-mono text-[12px]">
              Name matching ran; the model pass did not: {llmError}
            </div>
          )}
          {!error && (
            <>
              <DataTable
                columns={columns}
                rows={matches}
                emptyText={loading ? "Matching…" : "No destination columns."}
                selection={{
                  selectedIds: accepted,
                  rowId: (m) => m.dest,
                  onToggle: (id) =>
                    setAccepted((prev) => {
                      const next = new Set(prev);
                      if (next.has(id)) next.delete(id);
                      else next.add(id);
                      return next;
                    }),
                  onToggleAll: () =>
                    setAccepted((prev) =>
                      prev.size === matches.length
                        ? new Set()
                        : new Set(matches.map((m) => m.dest)),
                    ),
                }}
              />
              <div className="flex items-center justify-between px-3.5 py-3 border-t border-border">
                <span className="text-[12px] text-subtle">
                  Adds one select step at the end — the alias does the rename.
                </span>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="sm" onClick={onClose}>
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={apply}
                    disabled={loading || acceptedCount === 0}
                  >
                    Add {acceptedCount} mapping{acceptedCount === 1 ? "" : "s"}
                  </Button>
                </div>
              </div>
            </>
          )}
        </Panel>
      </div>
    </div>,
          document.body,
        );

  return (
    <>
      {/* Disabled with the reason attached rather than absent, so "why can't
          I auto-map?" is answered where it is asked. */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          setOpen(true);
          void propose();
        }}
        disabled={!outputId}
        title={outputId ? "Match source columns to the destination table" : "Pick a destination first"}
      >
        Auto-map…
      </Button>
      {dialog}
    </>
  );
}
