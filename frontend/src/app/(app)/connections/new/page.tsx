import { ConnectionForm } from "@/components/connection-form";
import type { Connection } from "@/lib/api";

const empty: Connection = {
  id: "",
  connection_type: "local_fs",
  credentials: {},
};

export default function NewConnectionPage() {
  return <ConnectionForm initial={empty} mode="create" />;
}
