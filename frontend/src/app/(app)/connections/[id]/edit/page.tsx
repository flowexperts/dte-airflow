import { notFound } from "next/navigation";
import { getConnection, ApiError } from "@/lib/api";
import { ConnectionForm } from "@/components/connection-form";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

export default async function EditConnectionPage({ params }: { params: Params }) {
  const { id } = await params;
  try {
    // reveal=false; user enters new creds on update if they want to change them.
    const connection = await getConnection(id, false);
    return <ConnectionForm initial={connection} mode="edit" />;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
