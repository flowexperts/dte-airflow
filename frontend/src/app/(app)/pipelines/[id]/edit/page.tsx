import { notFound } from "next/navigation";
import { BuilderForm } from "@/components/builder/BuilderForm";
import { RequirePermission } from "@/components/require-permission";
import { getPipeline, ApiError } from "@/lib/api";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

export default async function EditPipeline({ params }: { params: Params }) {
  const { id } = await params;
  try {
    const pipeline = await getPipeline(id);
    return (
      <RequirePermission perm="pipeline:write">
        <BuilderForm initial={pipeline} mode="edit" livePreview />
      </RequirePermission>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
