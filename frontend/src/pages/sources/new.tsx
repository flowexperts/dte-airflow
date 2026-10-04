import { SourceForm } from "@/components/source-form";
import { emptySource } from "@/components/builder/sources/types";
import { RequirePermission } from "@/components/require-permission";

export default function NewSourcePage() {
  return (
    <RequirePermission perm="source:write">
      <SourceForm initial={emptySource("")} mode="create" />
    </RequirePermission>
  );
}
