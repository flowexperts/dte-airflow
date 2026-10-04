import { useSearchParams } from "@/lib/nav";
import useSWR from "swr";
import { getSource } from "@/lib/api";
import { InlineError } from "@/components/ui";
import { MissingParam } from "@/components/missing-param";
import { withSuspense } from "@/components/with-suspense";
import { SourceForm } from "@/components/source-form";
import { RequirePermission } from "@/components/require-permission";

function EditSourcePage() {
  const id = useSearchParams().get("id");
  const { data, error } = useSWR(id ? ["source", id] : null, () => getSource(id!));
  if (!id) return <MissingParam what="source" />;
  if (error) {
    return (
      <div className="px-14 py-8">
        <InlineError title="Couldn't load this source" message="It may have been deleted." />
      </div>
    );
  }
  if (!data) return <div className="px-14 py-8 text-subtle font-mono text-sm">Loading…</div>;
  return (
    <RequirePermission perm="source:write">
      <SourceForm initial={data} mode="edit" />
    </RequirePermission>
  );
}

export default withSuspense(EditSourcePage);
