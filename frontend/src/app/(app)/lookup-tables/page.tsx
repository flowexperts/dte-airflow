import { PageHeader, Topbar } from "@/components/ui";
import { LookupTablesTable } from "@/components/lookup-tables-table";

export const dynamic = "force-dynamic";

export default function LookupTablesPage() {
  return (
    <>
      <Topbar
        crumbs={[{ label: "Workspace", href: "/" }, { label: "Lookup tables" }]}
      />
      <PageHeader
        title="Lookup tables"
        lede="Reusable key → value maps referenced by map/lookup steps across pipelines."
      />
      <div className="px-14 py-8">
        <LookupTablesTable />
      </div>
    </>
  );
}
