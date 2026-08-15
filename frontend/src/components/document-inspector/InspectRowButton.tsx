"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui";
import { inspectableRow } from "@/lib/inspect-row";
import { DocumentInspector } from "./DocumentInspector";

/**
 * The "Inspect" affordance on a row of extracted output.
 *
 * Renders nothing for rows with no document behind them, which is most rows
 * in most pipelines — so this can be dropped into any output table without
 * making non-document pipelines carry a dead column.
 *
 * A modal rather than a link because the provenance lives on the *row*: the
 * same PDF read by two `structure` configurations produces different fields,
 * so it cannot be recovered from a URL keyed on the document hash alone.
 */
export function InspectRowButton({ row }: { row: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const info = inspectableRow(row);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!info) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        // Named for screen readers and on hover: a bare glyph in a dense
        // table is unguessable, and this is the row's only way back to its
        // source document.
        aria-label={`Inspect ${info.filename ?? "document"}`}
        title={`Inspect ${info.filename ?? "document"}`}
        className="text-subtle hover:text-accent transition-colors align-middle"
      >
        <svg
          width="13"
          height="13"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="7" cy="7" r="4.5" />
          <path d="M10.5 10.5L14 14" />
        </svg>
      </button>

      {open &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-6"
            onClick={() => setOpen(false)}
          >
            <div
              className="w-full max-w-[1040px] rounded-md border border-border bg-surface p-5 shadow-lg"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-4 flex items-center justify-between gap-4">
                <div className="text-sm font-medium">
                  {info.filename ?? "Document"}
                </div>
                <Button size="sm" onClick={() => setOpen(false)} kbd="Esc">
                  Close
                </Button>
              </div>
              <DocumentInspector
                docKey={info.docKey}
                extractKey={info.extractKey}
                initialPage={info.page}
                fields={info.fields}
                filename={info.filename}
                // This modal is opened from run output and preview rows —
                // someone is checking an extracted value against the page,
                // which is exactly the judgement a label records. Capturing
                // it here is what stops eval sets from starting empty.
                labelable
              />
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
