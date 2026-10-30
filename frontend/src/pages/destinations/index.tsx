import useSWR from "swr";
import { InlineError, PageHeader, Topbar } from "@/components/ui";
import { listDestinations, type Destination } from "@/lib/api";
import { DestinationsTable } from "@/components/destinations-table";
import { NewResourceButton } from "@/components/new-resource-button";
import { humanizeError } from "@/lib/errors";

export default function DestinationsPage() {
  const { data, error } = useSWR<Destination[]>("destinations", () => listDestinations());
  const rows = data ?? [];
  const err = error ? humanizeError(error, { action: "load", entity: "destinations" }) : null;

  return (
    <>
      <Topbar
        crumbs={[{ label: "Admin" }, { label: "Destinations" }]}
        actions={
          <NewResourceButton
            perm="destination:write"
            href="/destinations/new"
            label="New destination"
          />
        }
      />
      <PageHeader
        title="Destinations"
        sub={`${rows.length} total`}
        lede="Reusable output targets. Pipelines write to one destination by id."
      />

      <div className="px-14 py-8">
        {err ? (
          <InlineError title={err.title} message={err.message} detail={err.detail} />
        ) : (
          <DestinationsTable rows={rows} />
        )}
      </div>
    </>
  );
}
