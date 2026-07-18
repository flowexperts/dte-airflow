"use client";

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { PageHeader, Panel, PanelHead, KV, KVItem, Tag, Button, Segmented } from "@/components/ui";
import { useTheme } from "@/components/theme-provider";
import { type CurrentUser, clearToken } from "@/lib/api";

export default function ProfilePage() {
  const router = useRouter();
  const { theme, set: setTheme } = useTheme();
  const { data: user, isLoading } = useSWR<CurrentUser>("/api/auth/me");

  function onLogout() {
    clearToken();
    router.replace("/login");
  }

  if (isLoading || !user) {
    return (
      <div className="p-6">
        <PageHeader title="Profile" />
        <p className="text-muted mt-6">Loading…</p>
      </div>
    );
  }

  const perms = [...user.permissions].sort();

  return (
    <div className="p-6 max-w-3xl">
      <PageHeader
        title="Profile"
        actions={
          <Button variant="ghost" onClick={onLogout}>
            Sign out
          </Button>
        }
      />

      <Panel className="mt-6">
        <PanelHead label="Account" />
        <div className="p-4">
          <KV>
            <KVItem label="Email" value={user.email} />
            <KVItem label="User ID" value={<span className="font-mono text-xs">{user.id}</span>} />
            <KVItem label="Status" value={user.is_active ? "Active" : "Disabled"} />
          </KV>
        </div>
      </Panel>

      <Panel className="mt-4">
        <PanelHead label="Roles" />
        <div className="p-4 flex flex-wrap gap-2">
          {user.roles.length === 0 ? (
            <span className="text-subtle text-sm">No roles assigned</span>
          ) : (
            user.roles.map((r) => <Tag key={r}>{r}</Tag>)
          )}
        </div>
      </Panel>

      <Panel className="mt-4">
        <PanelHead label="Appearance" />
        <div className="p-4 flex items-center justify-between">
          <span className="text-muted text-sm">Theme</span>
          <Segmented
            value={theme}
            onChange={setTheme}
            options={[
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
            ]}
          />
        </div>
      </Panel>

      <Panel className="mt-4">
        <PanelHead label="Permissions" count={perms.length} />
        <div className="p-4 flex flex-wrap gap-1.5">
          {perms.length === 0 ? (
            <span className="text-subtle text-sm">No permissions</span>
          ) : (
            perms.map((p) => (
              <span
                key={p}
                className="font-mono text-[11px] px-2 py-0.5 rounded-sm bg-surface-2 border border-border text-muted"
              >
                {p}
              </span>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}
