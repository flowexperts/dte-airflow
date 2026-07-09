import Link from "next/link";
import { cn } from "@/lib/cn";
import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme-toggle";

export function Sidebar({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <aside
      className={cn(
        "w-[220px] shrink-0 border-r border-border p-4 sticky top-0 h-screen",
        "bg-surface flex flex-col",
        className,
      )}
    >
      {children}
    </aside>
  );
}

export function Brand({
  version,
}: {
  version?: string;
}) {
  return (
    <div className="flex items-baseline gap-2 px-2">
      <span className="font-brand italic text-[26px] font-medium leading-none tracking-[-0.01em]">
        dt<em className="text-accent not-italic">e</em>
      </span>
      {version && (
        <span className="font-mono text-[9.5px] tracking-[0.18em] uppercase text-subtle border-l border-border pl-2 ml-0.5">
          {version}
        </span>
      )}
    </div>
  );
}

export function NavSearch({ shortcut = "⌘K" }: { shortcut?: string }) {
  return (
    <div className="mt-[18px] mb-2 flex items-center gap-2 px-2.5 py-1.5 bg-bg border border-border rounded-[var(--radius)] font-mono text-xs text-subtle">
      <span>Search…</span>
      <kbd className="ml-auto font-mono text-[10px] px-1.5 py-px bg-surface-2 border border-border rounded-sm text-subtle">
        {shortcut}
      </kbd>
    </div>
  );
}

export function NavSections({ children }: { children: ReactNode }) {
  return <nav className="mt-2 flex flex-col gap-px">{children}</nav>;
}

export function NavGroup({ children }: { children: ReactNode }) {
  return (
    <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-subtle px-2.5 pt-3.5 pb-1.5">
      {children}
    </div>
  );
}

export function NavItem({
  href,
  label,
  active,
  count,
}: {
  href: string;
  label: string;
  active?: boolean;
  count?: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-2.5 px-2.5 py-1.5 text-[13px] rounded-[var(--radius)] transition-colors no-underline",
        active
          ? "text-text bg-[color:var(--accent-tint)]"
          : "text-muted hover:text-text hover:bg-hover",
      )}
    >
      <span
        className={cn(
          "size-3.5 border rounded-sm inline-block",
          active
            ? "border-accent bg-accent"
            : "border-current opacity-50",
        )}
      />
      <span>{label}</span>
      {count !== undefined && (
        <span className="ml-auto font-mono text-[10.5px] text-subtle">
          {count}
        </span>
      )}
    </Link>
  );
}

export function NavFooter({
  live = true,
  children,
}: {
  live?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="mt-auto pt-3.5 border-t border-border flex items-center justify-between font-mono text-[10.5px] text-subtle">
      {live ? (
        <span className="flex items-center gap-1.5 text-green">
          <span className="size-1.5 rounded-full bg-green shadow-[0_0_6px_var(--green)] animate-pulse-live" />
          engine online
        </span>
      ) : (
        <span>offline</span>
      )}
      {children ?? <ThemeToggle />}
    </div>
  );
}
