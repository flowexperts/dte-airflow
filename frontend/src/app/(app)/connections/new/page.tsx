import { ConnectionForm } from "@/components/connection-form";
import { RequirePermission } from "@/components/require-permission";
import type { Connection } from "@/lib/api";

const empty: Connection = {
  id: "",
  connection_type: "local_fs",
  credentials: {},
};

export default function NewConnectionPage() {
  return (
    <RequirePermission perm="connection:write">
      <ConnectionForm initial={empty} mode="create" />
    </RequirePermission>
  );
}
