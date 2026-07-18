import { DestinationForm } from "@/components/destination-form";
import { RequirePermission } from "@/components/require-permission";
import type { Destination } from "@/lib/api";

const empty: Destination = {
  id: "",
  connection_id: "",
  config: { type: "json_file", path: "./out/result.json", fields: [] },
};

export default function NewDestinationPage() {
  return (
    <RequirePermission perm="destination:write">
      <DestinationForm initial={empty} mode="create" />
    </RequirePermission>
  );
}
