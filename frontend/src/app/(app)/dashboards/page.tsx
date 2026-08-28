import { DashboardsList } from "@/components/dashboards-list";

export const revalidate = 30; // list shell — SWR handles freshness client-side

export default function DashboardsPage() {
  return <DashboardsList />;
}
