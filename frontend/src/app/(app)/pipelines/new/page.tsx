import { BuilderForm } from "@/components/builder/BuilderForm";
import type { Pipeline } from "@/lib/api";

const empty: Pipeline = {
  id: "",
  name: "",
  sources: [],
  steps: [],
  output_id: "",
};

export default function NewPipeline() {
  return <BuilderForm initial={empty} mode="create" />;
}
