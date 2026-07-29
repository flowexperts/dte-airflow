import { InlineError, PageHeader, Topbar } from "@/components/ui";
import { listConnections, type Connection } from "@/lib/api";
import { ConnectionsTable } from "@/components/connections-table";
import { NewResourceButton } from "@/components/new-resource-button";
import { humanizeError, type HumanError } from "@/lib/errors";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side (P2 #26)

export default async function ConnectionsPage() {
  let connections: Connection[] = [];
  let error: HumanError | null = null;
  try {
    connections = await listConnections();
  } catch (e) {
    error = humanizeError(e, { action: "load", entity: "connections" });
  }

  return (
    <>
      <Topbar
        crumbs={[{ label: "Workspace", href: "/" }, { label: "Connections" }]}
        actions={
          <NewResourceButton perm="connection:write" href="/connections/new" label="New connection" />
        }
      />
      <PageHeader
        title="Connections"
        sub={`${connections.length} total`}
        lede="Credentials for your data infra. Sources and destinations bind to a connection by id."
      />

      <div className="px-14 py-8">
        {error ? (
          <InlineError title={error.title} message={error.message} detail={error.detail} />
        ) : (
          <ConnectionsTable rows={connections} />
        )}
      </div>
    </>
  );
}
