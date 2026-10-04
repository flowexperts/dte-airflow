import { useSearchParams } from "@/lib/nav";
import useSWR from "swr";
import { getDestination } from "@/lib/api";
import { InlineError } from "@/components/ui";
import { MissingParam } from "@/components/missing-param";
import { withSuspense } from "@/components/with-suspense";
import { DestinationForm } from "@/components/destination-form";
import { RequirePermission } from "@/components/require-permission";

function EditDestinationPage() {
  const id = useSearchParams().get("id");
  const { data, error } = useSWR(id ? ["destination", id] : null, () => getDestination(id!));
  if (!id) return <MissingParam what="destination" />;
  if (error) {
    return (
      <div className="px-14 py-8">
        <InlineError title="Couldn't load this destination" message="It may have been deleted." />
      </div>
    );
  }
  if (!data) return <div className="px-14 py-8 text-subtle font-mono text-sm">Loading…</div>;
  return (
    <RequirePermission perm="destination:write">
      <DestinationForm initial={data} mode="edit" />
    </RequirePermission>
  );
}

export default withSuspense(EditDestinationPage);
