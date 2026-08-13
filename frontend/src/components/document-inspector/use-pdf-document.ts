"use client";

import { useEffect, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { artifactAuthHeaders, artifactUrl } from "@/lib/api";

/**
 * Open a stored document with pdf.js, lazily.
 *
 * The options here are what make a 500-page PDF usable rather than a 40MB
 * download before the first page appears:
 *
 * - `httpHeaders` carries the bearer token, so the artifact route stays
 *   behind `run:read`. Handing pdf.js a bare URL would 401 — the browser
 *   attaches no Authorization header to a worker's own fetches.
 * - `disableAutoFetch` stops pdf.js from backgrounding a fetch of the whole
 *   file once it has the first page. Without it the range support on the
 *   server buys nothing.
 * - `disableStream: false` plus a modest `rangeChunkSize` keeps each request
 *   small, so paging deep into a document stays responsive.
 */
export function usePdfDocument(key: string | null) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    let task: { destroy: () => Promise<void> } | null = null;

    (async () => {
      setLoading(true);
      setError(null);
      try {
        // Dynamic import: pdf.js touches DOM globals at module scope, so a
        // static import would break the server render of any page that
        // merely links to the inspector.
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdfjs/pdf.worker.min.mjs";

        const t = pdfjs.getDocument({
          url: artifactUrl(key),
          httpHeaders: await artifactAuthHeaders(),
          disableAutoFetch: true,
          disableStream: false,
          rangeChunkSize: 64 * 1024,
        });
        task = t;
        const loaded = await t.promise;
        if (cancelled) {
          await t.destroy();
          return;
        }
        setDoc(loaded);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "could not open the document");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      // Tear the worker down on unmount; pdf.js holds one per document and
      // they do not get collected on their own.
      void task?.destroy();
    };
  }, [key]);

  return { doc, error, loading, pages: doc?.numPages ?? 0 };
}
