"use client";

import Link from "next/link";
import { Button } from "@/components/ui";
import { usePermissions } from "@/lib/use-permissions";

type Perm = Parameters<ReturnType<typeof usePermissions>["can"]>[0];

export function NewResourceButton({
  perm,
  href,
  label,
}: {
  perm: Perm;
  href: string;
  label: string;
}) {
  const { can } = usePermissions();
  if (!can(perm)) return null;
  return (
    <Link href={href}>
      <Button variant="primary" size="sm" kbd="N">
        {label}
      </Button>
    </Link>
  );
}
