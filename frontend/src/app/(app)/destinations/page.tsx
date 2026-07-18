import { PageHeader, Topbar } from "@/components/ui";
import { listDestinations, type Destination } from "@/lib/api";
import { DestinationsTable } from "@/components/destinations-table";
import { NewResourceButton } from "@/components/new-resource-button";

export const dynamic = "force-dynamic";

export default async function DestinationsPage() {
  let destinations: Destination[] = [];
  let error: string | null = null;
  try {
    destinations = await listDestinations();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <>
      <Topbar
        crumbs={[{ label: "Workspace", href: "/" }, { label: "Destinations" }]}
        actions={
          <NewResourceButton perm="destination:write" href="/destinations/new" label="New destination" />
        }
      />
      <PageHeader
        title="Destinations"
        sub={`${destinations.length} total`}
        lede="Reusable output targets. Pipelines write to one destination by id."
      />

      <div className="px-14 py-8">
        {error ? (
          <div className="p-4 border border-red rounded bg-code-bg text-red font-mono text-sm">
            Backend unreachable: {error}
          </div>
        ) : (
          <DestinationsTable rows={destinations} />
        )}
      </div>
    </>
  );
}
