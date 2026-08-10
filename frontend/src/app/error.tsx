"use client";

import { useEffect } from "react";
import { humanizeError } from "@/lib/errors";

/**
 * `redirect()` and `notFound()` signal by throwing, and this boundary sits
 * above them — so without this check a 401 bouncing to /login renders as the
 * literal string "NEXT_REDIRECT" instead of navigating. Re-throw so Next's
 * own handler upstream can act on it.
 *
 * Digest prefixes come from next/dist/client/components/redirect-error.js and
 * http-access-fallback.js.
 */
const isNextControlFlow = (e: { digest?: string }) =>
  typeof e.digest === "string" &&
  (e.digest.startsWith("NEXT_REDIRECT") ||
    e.digest.startsWith("NEXT_HTTP_ERROR_FALLBACK"));

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (isNextControlFlow(error)) return;
    console.error("App error boundary caught:", error);
  }, [error]);

  if (isNextControlFlow(error)) throw error;

  const human = humanizeError(error);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
      <h2 className="text-2xl font-semibold">{human.title}</h2>
      <p className="max-w-md text-sm text-muted">{human.message}</p>
      {(human.detail || error.digest) && (
        <details className="max-w-md text-left">
          <summary className="cursor-pointer font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-text">
            Show technical details
          </summary>
          {error.digest && (
            <div className="mt-2 font-mono text-xs text-subtle">ref: {error.digest}</div>
          )}
          {human.detail && (
            <pre className="mt-2 font-mono text-[11.5px] text-subtle whitespace-pre-wrap break-words max-h-56 overflow-auto">
              {human.detail}
            </pre>
          )}
        </details>
      )}
      <button
        onClick={reset}
        className="rounded-md border border-border bg-surface px-4 py-2 text-sm hover:bg-surface/70"
      >
        Try again
      </button>
    </div>
  );
}
