"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("App error boundary caught:", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
      <h2 className="text-2xl font-semibold">Something went wrong</h2>
      <p className="max-w-md text-sm text-muted">
        {error.message || "An unexpected error occurred."}
        {error.digest ? <span className="mt-2 block font-mono text-xs">ref: {error.digest}</span> : null}
      </p>
      <button
        onClick={reset}
        className="rounded-md border border-border bg-surface px-4 py-2 text-sm hover:bg-surface/70"
      >
        Try again
      </button>
    </div>
  );
}
