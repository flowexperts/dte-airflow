"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import {
  Sidebar,
  Brand,
  NavSections,
  NavGroup,
  NavItem,
  NavFooter,
} from "@/components/ui";
import { type CurrentUser, type Pipeline, clearToken } from "@/lib/api";
import { PIPELINE_TYPE_TABS, type PipelineTypeFilter } from "@/lib/pipeline-type";

export function AppSidebar() {
  const pathname = usePathname() ?? "";
  // usePathname() excludes the query string, so the old
  // `pathname.includes("type=quality")` test never matched and neither
  // sub-item ever highlighted.
  const typeParam = useSearchParams()?.get("type") ?? null;
  const router = useRouter();
  const on = (prefix: string) =>
    prefix === "/"
      ? pathname === "/"
      : pathname === prefix || pathname.startsWith(prefix + "/");

  const { data: user } = useSWR<CurrentUser>("/api/auth/me");

  /* A pipeline detail page (`/pipelines/<id>`, `/edit`, `/compare`,
     `/revisions/<rev>`) carries no `?type=` — that query param only exists
     on the list page. Without knowing the pipeline's own type, every detail
     page fell through to the "no filter" default below and permanently
     highlighted Transform, including for a quality or eval pipeline. */
  const detailMatch = /^\/pipelines\/([^/]+)/.exec(pathname);
  const detailSegment = detailMatch?.[1];
  const detailId =
    detailSegment && detailSegment !== "new" ? decodeURIComponent(detailSegment) : null;
  const { data: currentPipeline } = useSWR<Pipeline>(
    detailId ? `/api/pipelines/${encodeURIComponent(detailId)}` : null,
  );

  const activePipelineType: PipelineTypeFilter | null = detailId
    ? currentPipeline
      ? ((currentPipeline.pipeline_type as PipelineTypeFilter | undefined) ?? "transform")
      : null // unknown until it loads — no highlight beats a wrong one
    : on("/pipelines") && !on("/pipelines/new")
      ? ((typeParam as PipelineTypeFilter | null) ?? "transform")
      : null;

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
        {can("dashboard:read") && (
          <NavItem href="/dashboards" label="Dashboards" active={on("/dashboards")} />
        )}
        {can("eval:read") && (
          <NavItem href="/eval-sets" label="Eval sets" active={on("/eval-sets")} />
        )}
        {can("pipeline:read") && (
          <>
            <NavGroup>Pipelines</NavGroup>
            {/* Driven by PIPELINE_TYPE_TABS so a new pipeline_type cannot
                ship without a way back to it. Eval pipelines were creatable
                in the builder and reachable from nowhere: both links carry a
                ?type=, so no nav path produced the unfiltered list. */}
            {PIPELINE_TYPE_TABS.map(({ type, label }) => (
              <NavItem
                key={type}
                href={`/pipelines?type=${type}`}
                label={label}
                indent
                active={activePipelineType === type}
              />
            ))}
            {/* No "+ New pipeline" here. Creation belongs on the list page,
                where the primary button sits beside the thing being added.
                In the nav it read as a third kind of pipeline next to
                Transform and Quality Check. */}
          </>
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
