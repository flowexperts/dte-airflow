import { PageHeader, Topbar } from "@/components/ui";
import { listConnections, type Connection } from "@/lib/api";
import { ConnectionsTable } from "@/components/connections-table";
import { NewResourceButton } from "@/components/new-resource-button";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side (P2 #26)

export default async function ConnectionsPage() {
  let connections: Connection[] = [];
  let error: string | null = null;
  try {
    connections = await listConnections();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
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
          <div className="p-4 border border-red rounded bg-code-bg text-red font-mono text-sm">
            Backend unreachable: {error}
          </div>
        ) : (
          <ConnectionsTable rows={connections} />
        )}
      </div>
    </>
  );
}
