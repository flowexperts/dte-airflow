"use client";

import { usePathname } from "next/navigation";
import {
  Sidebar,
  Brand,
  NavSearch,
  NavSections,
  NavGroup,
  NavItem,
  NavFooter,
} from "@/components/ui";

export function AppSidebar() {
  const pathname = usePathname() ?? "";
  const on = (prefix: string) =>
    prefix === "/"
      ? pathname === "/"
      : pathname === prefix || pathname.startsWith(prefix + "/");

  return (
    <Sidebar>
      <Brand version="v0.1" />
      <NavSearch />
      <NavSections>
        <NavGroup>Workspace</NavGroup>
        <NavItem href="/connections" label="Connections" active={on("/connections")} />
        <NavItem href="/sources" label="Sources" active={on("/sources")} />
        <NavItem href="/destinations" label="Destinations" active={on("/destinations")} />
        <NavItem href="/pipelines" label="Pipelines" active={on("/pipelines")} />
        <NavGroup>System</NavGroup>
        <NavItem href="/preview" label="Design" active={on("/preview")} />
      </NavSections>
      <NavFooter />
    </Sidebar>
  );
}
