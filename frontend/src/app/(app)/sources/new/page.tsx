import { SourceForm } from "@/components/source-form";
import { emptySource } from "@/components/builder/sources/types";

export default function NewSourcePage() {
  return <SourceForm initial={emptySource("")} mode="create" />;
}
