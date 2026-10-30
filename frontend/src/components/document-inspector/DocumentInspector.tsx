import { useEffect, useMemo, useState } from "react";
import { Button, ErrorPanel, Panel, PanelHead } from "@/components/ui";
import { getExtractedBlocks, type ExtractedBlock } from "@/lib/api";
import { resolveHighlight, type Provenance, type Rect } from "@/lib/provenance";
import { usePdfDocument } from "./use-pdf-document";
import { PdfPageCanvas } from "./PdfPageCanvas";
import { LabelFromInspector } from "@/components/evals/label-from-inspector";

export interface InspectorField {
  name: string;
  value: unknown;
  provenance?: Provenance | null;
}

const PAGE_WIDTH = 620;

export function DocumentInspector({
  docKey,
  extractKey,
  initialPage = 1,
  fields = [],
  filename,
  labelable = false,
}: {
  docKey: string;
  extractKey?: string | null;
  initialPage?: number;
  fields?: InspectorField[];
  filename?: string | null;
  /** Offer "use this as ground truth". Off by default — the inspector is
   *  also opened in read-only contexts where labeling would be noise. */
  labelable?: boolean;
}) {
  const { doc, error, loading, pages } = usePdfDocument(docKey);
  const [page, setPage] = useState(initialPage);
  const [selected, setSelected] = useState<string | null>(
    fields.find((f) => f.provenance?.quote)?.name ?? null,
  );
  const [blocks, setBlocks] = useState<ExtractedBlock[]>([]);
  const [blocksErr, setBlocksErr] = useState<string | null>(null);

  useEffect(() => {
    if (!extractKey) return;
    let cancelled = false;
    getExtractedBlocks(extractKey)
      .then((b) => !cancelled && setBlocks(b))
      .catch(
        (e) =>
          !cancelled && setBlocksErr(e instanceof Error ? e.message : "could not load word boxes"),
      );
    return () => {
      cancelled = true;
    };
  }, [extractKey]);

  const field = fields.find((f) => f.name === selected) ?? null;
  const prov = field?.provenance ?? null;

  /** Select a field and jump to the page it came from.
   *
   *  In the handler rather than an effect: the jump is a consequence of the
   *  click, not of the render. As an effect it would also re-fire whenever
   *  the selected field's provenance changed underneath, yanking the page
   *  out from under someone who had since paged elsewhere.
   */
  const select = (f: InspectorField) => {
    setSelected(f.name);
    if (f.provenance?.page) setPage(f.provenance.page);
  };

  const highlights: Rect[] = useMemo(() => {
    if (!prov?.quote) return [];
    // Blocks are per page at page granularity; at document granularity there
    // is one block carrying every word, and its `page` is null.
    const only = blocks.length === 1 ? blocks[0] : undefined;
    const block = blocks.find((b) => b.page === page) ?? (only && only.page === null ? only : null);
    if (!block) return [];
    return resolveHighlight(block, prov);
  }, [blocks, page, prov]);

  const unlocatable = Boolean(prov?.quote) && highlights.length === 0;

  return (
    <div className="grid grid-cols-[1fr_320px] gap-5 items-start">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || !doc}
          >
            ← Prev
          </Button>
          <span className="text-[12.5px] text-subtle font-mono">
            {loading ? "opening…" : `page ${page}${pages ? ` / ${pages}` : ""}`}
          </span>
          <Button
            size="sm"
            onClick={() => setPage((p) => Math.min(pages || p, p + 1))}
            disabled={!pages || page >= pages || !doc}
          >
            Next →
          </Button>
          {filename && (
            <span className="ml-2 text-[12.5px] text-subtle font-mono truncate">{filename}</span>
          )}
        </div>

        {error && (
          <ErrorPanel
            title="Could not open the document"
            message={error}
            detail={`artifact ${docKey.slice(0, 12)}…`}
          />
        )}

        {doc && !error && (
          <PdfPageCanvas doc={doc} page={page} highlights={highlights} width={PAGE_WIDTH} />
        )}
      </div>

      <Panel>
        <PanelHead label="Extracted fields" />
        <div className="flex flex-col">
          {fields.length === 0 && (
            <p className="px-4 py-3 text-[12.5px] text-subtle">
              No structured fields on this row — showing the document only.
            </p>
          )}

          {fields.map((f) => {
            const p = f.provenance ?? null;
            const active = f.name === selected;
            return (
              <button
                key={f.name}
                type="button"
                onClick={() => select(f)}
                className={`text-left px-4 py-2.5 border-b border-border-2 last:border-b-0 transition-colors ${
                  active ? "bg-surface-2" : "hover:bg-surface-2/60"
                }`}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[12.5px] text-subtle font-mono">{f.name}</span>
                  {typeof p?.confidence === "number" && (
                    <span className="text-[11px] text-subtle tabular-nums">
                      {(p.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
                <div className="text-[13px] text-text break-words">
                  {f.value === null || f.value === undefined ? (
                    <span className="text-subtle">null</span>
                  ) : (
                    String(f.value)
                  )}
                </div>
                {p?.page && <div className="mt-0.5 text-[11px] text-subtle">page {p.page}</div>}
                {active && !p?.quote && f.value !== null && (
                  // The acceptance rule: a paraphrased value has no span, and
                  // saying so is required. Boxing an approximation would be a
                  // confident lie about where a number came from.
                  <div className="mt-1 text-[11px] text-gold">
                    No source span — this value was inferred, not quoted.
                  </div>
                )}
                {active && unlocatable && (
                  <div className="mt-1 text-[11px] text-gold">
                    Quoted “{p?.quote}” but it could not be located on the page.
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </Panel>

      {labelable && (
        <div className="col-span-2">
          <LabelFromInspector
            docKey={docKey}
            docRef={filename ?? null}
            values={Object.fromEntries(fields.map((f) => [f.name, f.value]))}
          />
        </div>
      )}

      {blocksErr && (
        <div className="col-span-2">
          <ErrorPanel
            title="Highlights unavailable"
            message={blocksErr}
            detail="The page still renders; only the boxes are missing."
          />
        </div>
      )}
    </div>
  );
}
