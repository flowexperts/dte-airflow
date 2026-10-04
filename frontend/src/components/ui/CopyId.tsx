import { useState } from "react";

export function CopyId({ id, shorten }: { id: string; shorten?: boolean }) {
  const [copied, setCopied] = useState(false);

  const copy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(id).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <span className="flex items-center gap-1 min-w-0 pr-4">
      <span className="font-mono text-[11.5px] text-subtle truncate">
        {shorten ? id.slice(0, 8) + "…" : id}
      </span>
      <button
        type="button"
        onClick={copy}
        title="Copy ID"
        className="shrink-0 text-subtle hover:text-text transition-colors"
      >
        {copied ? (
          <span className="font-mono text-[10px] text-green">✓</span>
        ) : (
          <svg
            width="11"
            height="11"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="opacity-50 hover:opacity-100"
          >
            <rect x="5" y="5" width="9" height="9" rx="1.5" />
            <path d="M11 5V3.5A1.5 1.5 0 0 0 9.5 2h-6A1.5 1.5 0 0 0 2 3.5v6A1.5 1.5 0 0 0 3.5 11H5" />
          </svg>
        )}
      </button>
    </span>
  );
}
