"use client";

import useSWR from "swr";
import type { CurrentUser } from "./api";

type Resource = "pipeline" | "connection" | "source" | "destination" | "lookup_table" | "dashboard" | "run" | "user" | "eval";
type Action = "read" | "write" | "delete" | "trigger" | "test";

export function usePermissions() {
  const { data, isLoading } = useSWR<CurrentUser>("/api/auth/me");
  const perms = data?.permissions ?? [];
  return {
    isLoading,
    isAuthenticated: !!data,
    can: (perm: `${Resource}:${Action}`) => perms.includes(perm),
  };
}
