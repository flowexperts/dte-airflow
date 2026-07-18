"use client";

import type { ReactNode } from "react";
import { usePermissions } from "@/lib/use-permissions";

type Perm = Parameters<ReturnType<typeof usePermissions>["can"]>[0];

export function RequirePermission({
  perm,
  children,
}: {
  perm: Perm;
  children: ReactNode;
}) {
  const { can, isLoading } = usePermissions();
  if (isLoading) return null;
  if (!can(perm)) {
    return (
      <div className="px-14 py-16">
        <div className="max-w-xl border border-border rounded bg-surface p-6">
          <div className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle mb-2">
            Permission required
          </div>
          <div className="text-lg font-medium mb-1">You don&apos;t have access to this page.</div>
          <div className="text-sm text-muted">
            This action requires the <code className="font-mono text-[12px]">{perm}</code> permission.
            Ask an admin to update your role.
          </div>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
