import { notFound } from "next/navigation";
import { getSource, ApiError } from "@/lib/api";
import { SourceForm } from "@/components/source-form";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

export default async function EditSourcePage({ params }: { params: Params }) {
  const { id } = await params;
  try {
    const source = await getSource(id);
    return <SourceForm initial={source} mode="edit" />;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
