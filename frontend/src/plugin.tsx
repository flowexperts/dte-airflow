/**
 * Airflow `react_apps` entry (plan 066). Airflow renders this default export
 * inside its own layout at `plugin/:page/*`, with its React and router —
 * so DTE shares Airflow's page, theme and fonts instead of sitting in an
 * iframe. Every nav entry in plugin.py loads this one bundle; `:page` says
 * which section it was opened as.
 */
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import css from "./dte.css?inline";
import { ErrorBoundary } from "@/components/error-boundary";
import { Toaster } from "@/components/toaster";
import { SwrProvider } from "@/lib/swr-config";
import Destinations from "@/pages/destinations";
import DestinationEdit from "@/pages/destinations/edit";
import DestinationNew from "@/pages/destinations/new";
import DocumentDetail from "@/pages/documents/detail";
import LookupTables from "@/pages/lookup-tables";
import Pipelines from "@/pages/pipelines";
import PipelineDetail from "@/pages/pipelines/detail";
import PipelineNew from "@/pages/pipelines/new";
import PipelineRevision from "@/pages/pipelines/revision";
import Preview from "@/pages/preview";
import RunDetail from "@/pages/runs/detail";
import Sources from "@/pages/sources";
import SourceEdit from "@/pages/sources/edit";
import SourceNew from "@/pages/sources/new";

if (typeof document !== "undefined" && !document.getElementById("dte-styles")) {
  const style = document.createElement("style");
  style.id = "dte-styles";
  style.textContent = css;
  document.head.appendChild(style);
}

function Landing() {
  // `dte` → pipelines; `dte-sources` → sources, and so on.
  const page = useParams().page ?? "dte";
  // The Quality Check menu entry is a filter of the `dte` list, not a section.
  if (page === "dte-quality") return <Navigate to="/plugin/dte/pipelines?type=quality" replace />;
  const section = page.replace(/^dte-?/, "") || "pipelines";
  // Absolute: the `*` fallback reuses this, and a relative target there
  // appends to the unknown path, redirecting forever.
  return <Navigate to={`/plugin/${page}/${section}`} replace />;
}

function Shell() {
  const routes = (
    <ErrorBoundary>
      <Routes>
        <Route index element={<Landing />} />
        <Route path="pipelines" element={<Pipelines />} />
        <Route path="pipelines/new" element={<PipelineNew />} />
        <Route path="pipelines/detail" element={<PipelineDetail />} />
        <Route path="pipelines/revision" element={<PipelineRevision />} />
        <Route path="runs/detail" element={<RunDetail />} />
        <Route path="sources" element={<Sources />} />
        <Route path="sources/new" element={<SourceNew />} />
        <Route path="sources/edit" element={<SourceEdit />} />
        <Route path="destinations" element={<Destinations />} />
        <Route path="destinations/new" element={<DestinationNew />} />
        <Route path="destinations/edit" element={<DestinationEdit />} />
        <Route path="lookup-tables" element={<LookupTables />} />
        <Route path="documents/detail" element={<DocumentDetail />} />
        <Route path="preview" element={<Preview />} />
        <Route path="*" element={<Landing />} />
      </Routes>
    </ErrorBoundary>
  );
  // No DTE sidebar: Airflow's rail is the navigation (plan 067).
  return <main className="min-w-0">{routes}</main>;
}

export default function DtePlugin() {
  return (
    <div className="dte-root h-full">
      <SwrProvider>
        <Toaster>
          <Shell />
        </Toaster>
      </SwrProvider>
    </div>
  );
}

// Airflow 3.3 clears `globalThis.AirflowPlugin` before each `import()` and
// looks the component up by the react_app's `name`. Every DTE entry shares
// this bundle, which the browser runs once, so register under every name up
// front. Must match plugin.py's names (checked by test_plugin_names.py).
const ENTRY_NAMES = [
  "Transform",
  "Quality Check",
  "DTE Sources",
  "DTE Destinations",
  "DTE Lookup tables",
];
for (const name of ENTRY_NAMES) (globalThis as Record<string, unknown>)[name] = DtePlugin;
