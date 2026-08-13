"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import type { Rect } from "@/lib/provenance";

/**
 * One rendered page with provenance boxes over it.
 *
 * Rects arrive as fractions of the page (see `provenance.ts`), so the overlay
 * is plain positioned divs rather than canvas drawing — they survive a
 * re-render at a different zoom without recomputing anything, and they can
 * carry a title and a hover state.
 */
export function PdfPageCanvas({
  doc,
  page,
  highlights,
  width,
}: {
  doc: PDFDocumentProxy;
  page: number;
  highlights: Rect[];
  width: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // pdf.js throws if two render() calls share a canvas, which is exactly
    // what a fast page change does — keep the handle so it can be cancelled.
    let task: { cancel: () => void; promise: Promise<void> } | null = null;

    (async () => {
      try {
        const p = await doc.getPage(page);
        if (cancelled) return;

        const base = p.getViewport({ scale: 1 });
        const scale = width / base.width;
        const viewport = p.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;

        // Render at device resolution and scale down with CSS, or the page is
        // visibly soft on any HiDPI screen — which matters when the point is
        // reading a number off an invoice.
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        setSize({ w: viewport.width, h: viewport.height });

        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        task = p.render({ canvas, canvasContext: ctx, viewport });
        await task.promise;
      } catch (e) {
        // A cancelled render is the normal result of paging, not a failure.
        const name = e instanceof Error ? e.name : "";
        if (!cancelled && name !== "RenderingCancelledException") {
          setErr(e instanceof Error ? e.message : "could not render this page");
        }
      }
    })();

    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, page, width]);

  return (
    <div className="relative inline-block bg-white shadow-sm rounded-[var(--radius)] overflow-hidden">
      <canvas ref={canvasRef} className="block" />

      {size &&
        highlights.map((r, i) => (
          <div
            key={i}
            aria-hidden
            className="absolute pointer-events-none rounded-[2px] bg-[color-mix(in_srgb,var(--accent)_28%,transparent)] ring-1 ring-[var(--accent)]"
            style={{
              left: r.x * size.w,
              top: r.y * size.h,
              width: r.w * size.w,
              height: r.h * size.h,
            }}
          />
        ))}

      {err && (
        <div className="absolute inset-0 grid place-items-center bg-surface/90 text-[12.5px] text-red px-6 text-center">
          {err}
        </div>
      )}
    </div>
  );
}
