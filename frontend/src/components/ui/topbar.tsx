import { cn } from "@/lib/cn";
import type { ReactNode } from "react";
import { Link } from "@/lib/nav";

export interface Crumb {
  label: string;
  href?: string;
}

export function Topbar({
  crumbs,
  actions,
  className,
}: {
  crumbs: Crumb[];
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "h-13 min-h-[52px] px-14 border-b border-border bg-surface sticky top-0 z-20",
        "flex items-center justify-between backdrop-blur-sm",
        className,
      )}
    >
      <nav className="flex items-center gap-2 text-[13px]">
        {crumbs.map((c, i) => {
          const isLast = i === crumbs.length - 1;
          return (
            <span key={i} className="flex items-center gap-2">
              {i > 0 && <span className="text-subtle opacity-50">/</span>}
              {c.href && !isLast ? (
                <Link
                  href={c.href}
                  className="text-subtle hover:text-text no-underline"
                >
                  {c.label}
                </Link>
              ) : (
                <span
                  className={isLast ? "text-text font-medium" : "text-subtle"}
                >
                  {c.label}
                </span>
              )}
            </span>
          );
        })}
      </nav>
      {actions && <div className="flex items-center gap-2.5">{actions}</div>}
    </div>
  );
}
