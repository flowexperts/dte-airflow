import { Suspense } from "react";
import { AppSidebar } from "@/components/app-sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[220px_1fr] min-h-screen">
      {/* AppSidebar reads useSearchParams() to highlight the active Pipelines
          sub-item. Without a Suspense boundary that opts every statically
          generated page in this group out of prerendering. */}
      <Suspense fallback={<div className="border-r border-border bg-surface" />}>
        <AppSidebar />
      </Suspense>
      <main>{children}</main>
    </div>
  );
}
