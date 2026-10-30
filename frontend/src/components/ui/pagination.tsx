import { cn } from "@/lib/cn";

/**
 * Offset pager for list panes.
 *
 * Numbered rather than "Load more" on purpose: the count is the point. "1–20
 * of 1,284" tells you the scale of what you are looking at before you decide
 * whether to look further, and an endless append button never does — you can
 * click it forever without learning whether you are near the end.
 *
 * Renders nothing when everything fits on one page, so short lists carry no
 * chrome at all.
 */
export function Pagination({
  total,
  limit,
  offset,
  onChange,
  className,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (nextOffset: number) => void;
  className?: string;
}) {
  if (total <= limit) return null;

  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  const first = offset + 1;
  const last = Math.min(offset + limit, total);

  const go = (p: number) => onChange((Math.min(Math.max(1, p), pages) - 1) * limit);

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 px-3.5 py-2.5 border-t border-border",
        className,
      )}
    >
      <span className="font-mono text-[11px] text-subtle tabular-nums">
        {first.toLocaleString()}–{last.toLocaleString()} of {total.toLocaleString()}
      </span>
      <div className="flex items-center gap-1">
        <PageButton onClick={() => go(1)} disabled={page === 1} label="First page">
          «
        </PageButton>
        <PageButton onClick={() => go(page - 1)} disabled={page === 1} label="Previous page">
          ‹
        </PageButton>
        <span className="font-mono text-[11px] text-muted px-2 tabular-nums">
          {page} / {pages}
        </span>
        <PageButton onClick={() => go(page + 1)} disabled={page >= pages} label="Next page">
          ›
        </PageButton>
        <PageButton onClick={() => go(pages)} disabled={page >= pages} label="Last page">
          »
        </PageButton>
      </div>
    </div>
  );
}

function PageButton({
  onClick,
  disabled,
  label,
  children,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className={cn(
        "size-6 rounded-[var(--radius)] text-[12px] leading-none transition-colors",
        disabled ? "text-subtle/40 cursor-default" : "text-muted hover:text-accent hover:bg-hover",
      )}
    >
      {children}
    </button>
  );
}
