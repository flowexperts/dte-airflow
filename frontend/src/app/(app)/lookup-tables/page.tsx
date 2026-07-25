import { LookupTablesTable } from "@/components/lookup-tables-table";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side (P2 #26)

export default function LookupTablesPage() {
  return <LookupTablesTable />;
}
