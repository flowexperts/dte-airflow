import { DashboardDetail } from "@/components/dashboard/dashboard-detail";

/**
 * Server shell only. Every affordance on this surface owns a handler — tile
 * editors, save, reorder — so the whole interactive tree is one client
 * component the page composes, never a function prop passed across the
 * boundary.
 */
export default async function DashboardPage({ params }: PageProps<"/dashboards/[id]">) {
  const { id } = await params;
  return <DashboardDetail id={id} />;
}
