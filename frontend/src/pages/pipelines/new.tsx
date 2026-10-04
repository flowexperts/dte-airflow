import { BuilderForm } from "@/components/builder/BuilderForm";
import { RequirePermission } from "@/components/require-permission";
import type { Pipeline } from "@/lib/api";

const empty: Pipeline = {
  id: "",
  name: "",
  sources: [],
  steps: [],
  output_id: "",
};

export default function NewPipeline() {
  return (
    <RequirePermission perm="pipeline:write">
      <BuilderForm initial={empty} />
    </RequirePermission>
  );
}
