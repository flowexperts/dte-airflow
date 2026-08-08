"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { cn } from "@/lib/cn";
import type { Variant, VariantOption } from "./_variant-util";

/**
 * Sticky layout switcher. Swaps only the `v` query param so you stay on the
 * same real pipeline while comparing layouts — that's the whole point of /lab.
 * Every other param (notably `edit`) rides along untouched.
 */
export function VariantBar({
  options,
  current,
}: {
  options: VariantOption[];
  current: Variant;
}) {
  const pathname = usePathname();
  const search = useSearchParams();

  const hrefFor = (v: Variant) => {
    const next = new URLSearchParams(search.toString());
    next.set("v", v);
    return `${pathname}?${next.toString()}`;
  };

  const active = options.find((o) => o.value === current);

  return (
    <div className="sticky top-[52px] z-10 flex items-center gap-3 px-14 py-2 border-b border-border bg-surface-2">
      <span className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle shrink-0">
        Layout
      </span>
      <div className="flex items-center gap-1">
        {options.map((o) => (
          <Link
            key={o.value}
            href={hrefFor(o.value)}
            scroll={false}
            aria-current={o.value === current ? "true" : undefined}
            className={cn(
              "px-2.5 py-1 rounded-sm no-underline transition-colors",
              "font-mono text-[10.5px] tracking-[0.15em] uppercase",
              o.value === current
                ? "text-accent bg-[color:var(--accent-tint)]"
                : "text-subtle hover:text-text hover:bg-hover",
            )}
          >
            {o.value} · {o.label}
          </Link>
        ))}
      </div>
      {active && (
        <span className="text-[12px] text-subtle truncate">{active.note}</span>
      )}
    </div>
  );
}
