import { notFound } from "next/navigation";
import { getDestination, ApiError } from "@/lib/api";
import { DestinationForm } from "@/components/destination-form";
import { RequirePermission } from "@/components/require-permission";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

export default async function EditDestinationPage({ params }: { params: Params }) {
  const { id } = await params;
  try {
    const destination = await getDestination(id);
    return (
      <RequirePermission perm="destination:write">
        <DestinationForm initial={destination} mode="edit" />
      </RequirePermission>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
