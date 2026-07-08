import { BuilderForm } from "@/components/builder/BuilderForm";
import type { Pipeline } from "@/lib/api";

const empty: Pipeline = {
  id: "",
  name: "",
  sources: [],
  steps: [],
  output: { type: "json_file", path: "./out/result.json", fields: [] },
};

export default function NewPipeline() {
  return <BuilderForm initial={empty} mode="create" />;
}
