import { Link } from "@/lib/nav";
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
  const { can, isLoading } = usePermissions();

  /* Render while permissions are still in flight. `can()` reads an empty
   * permission list until /api/me resolves, so gating on it alone hides
   * the primary create action on first paint — and hides it permanently if
   * that request fails. The server still authorises the actual write; this
   * button is a signpost, not the gate. */
  if (!isLoading && !can(perm)) return null;

  return (
    <Link href={href}>
      <Button variant="primary" size="sm" kbd="N">
        {label}
      </Button>
    </Link>
  );
}
