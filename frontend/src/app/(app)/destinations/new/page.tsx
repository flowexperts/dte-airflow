import { DestinationForm } from "@/components/destination-form";
import type { Destination } from "@/lib/api";

const empty: Destination = {
  id: "",
  config: { type: "json_file", path: "./out/result.json", fields: [] },
};

export default function NewDestinationPage() {
  return <DestinationForm initial={empty} mode="create" />;
}
