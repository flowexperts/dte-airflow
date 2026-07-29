"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import useSWR from "swr";
import {
  Sidebar,
  Brand,
  NavSections,
  NavGroup,
  NavItem,
  NavFooter,
} from "@/components/ui";
import { type CurrentUser, clearToken } from "@/lib/api";

export function AppSidebar() {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const on = (prefix: string) =>
    prefix === "/"
      ? pathname === "/"
      : pathname === prefix || pathname.startsWith(prefix + "/");

  const { data: user } = useSWR<CurrentUser>("/api/auth/me");

  function onLogout() {
    clearToken();
    router.replace("/login");
  }

  const perms = new Set(user?.permissions ?? []);
  const can = (perm: string) => (user ? perms.has(perm) : true);

  const initial = user?.email?.[0]?.toUpperCase() ?? "?";

  return (
    <Sidebar>
      <Brand version="v0.1" />
      <NavSections>
        <NavGroup>Workspace</NavGroup>
        {can("connection:read") && (
          <NavItem href="/connections" label="Connections" active={on("/connections")} />
        )}
        {can("source:read") && (
          <NavItem href="/sources" label="Sources" active={on("/sources")} />
        )}
        {can("destination:read") && (
          <NavItem href="/destinations" label="Destinations" active={on("/destinations")} />
        )}
        {can("lookup_table:read") && (
          <NavItem href="/lookup-tables" label="Lookup tables" active={on("/lookup-tables")} />
        )}
        {can("pipeline:read") && (
          <NavItem href="/pipelines" label="Pipelines" active={on("/pipelines")} />
        )}
      </NavSections>
      <NavFooter>
        <span />
      </NavFooter>
      {user ? (
        <div className="mt-2 pt-3 border-t border-border flex items-center gap-2">
          <Link
            href="/profile"
            className={`flex items-center gap-2 flex-1 min-w-0 px-2 py-1.5 rounded-[var(--radius)] no-underline transition-colors ${
              on("/profile")
                ? "bg-[color:var(--accent-tint)] text-text"
                : "text-muted hover:text-text hover:bg-hover"
            }`}
            title="Profile"
          >
            <span className="size-6 rounded-full bg-accent text-bg font-mono text-[11px] flex items-center justify-center shrink-0">
              {initial}
            </span>
            <span className="truncate font-mono text-[11.5px]" title={user.email}>
              {user.email}
            </span>
          </Link>
          <button
            type="button"
            onClick={onLogout}
            className="text-subtle hover:text-text font-mono text-[10px] uppercase tracking-[0.18em]"
            title="Sign out"
          >
            Out
          </button>
        </div>
      ) : null}
    </Sidebar>
  );
}
