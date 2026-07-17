"use client";

import { usePathname, useRouter } from "next/navigation";
import useSWR from "swr";
import {
  Sidebar,
  Brand,
  NavSearch,
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
  // Before /auth/me resolves, don't hide anything — otherwise the sidebar
  // flickers on every page load. Once we have data, gate each item.
  const can = (perm: string) => (user ? perms.has(perm) : true);

  return (
    <Sidebar>
      <Brand version="v0.1" />
      <NavSearch />
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
        {can("user:read") && (
          <>
            <NavGroup>Admin</NavGroup>
            <NavItem href="/users" label="Users" active={on("/users")} />
          </>
        )}
        <NavGroup>System</NavGroup>
        <NavItem href="/preview" label="Design" active={on("/preview")} />
      </NavSections>
      {user ? (
        <div className="mt-3 mb-2 flex items-center justify-between text-xs px-1">
          <span className="truncate text-muted font-mono" title={user.email}>
            {user.email}
          </span>
          <button
            type="button"
            onClick={onLogout}
            className="text-subtle hover:text-text font-mono text-[10.5px] uppercase tracking-[0.18em] ml-2"
          >
            Sign out
          </button>
        </div>
      ) : null}
      <NavFooter />
    </Sidebar>
  );
}
