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

  return (
    <Sidebar>
      <Brand version="v0.1" />
      <NavSearch />
      <NavSections>
        <NavGroup>Workspace</NavGroup>
        <NavItem href="/connections" label="Connections" active={on("/connections")} />
        <NavItem href="/sources" label="Sources" active={on("/sources")} />
        <NavItem href="/destinations" label="Destinations" active={on("/destinations")} />
        <NavItem href="/lookup-tables" label="Lookup tables" active={on("/lookup-tables")} />
        <NavItem href="/pipelines" label="Pipelines" active={on("/pipelines")} />
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
