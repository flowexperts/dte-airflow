import { EvalSetForm } from "@/components/evals/eval-set-form";
import { RequirePermission } from "@/components/require-permission";

export default function NewEvalSetPage() {
  return (
    <RequirePermission perm="eval:write">
      <EvalSetForm />
    </RequirePermission>
  );
}
