"use client";

import {
  Button,
  Pill,
  Panel,
  PanelHead,
  PageHeader,
  SectionHead,
  Topbar,
  Sidebar,
  Brand,
  NavSearch,
  NavSections,
  NavGroup,
  NavItem,
  NavFooter,
  DataTable,
  StepRow,
  ExprCode,
  ExprToken,
  KV,
  KVItem,
  AddStep,
  Item,
  Tag,
  Metric,
  MetricRow,
  Timeline,
  TimelineRow,
  InlineCode,
} from "@/components/ui";
import type { Column } from "@/components/ui";
import { ThemeToggle } from "@/components/theme-toggle";

interface PipelineRow {
  idx: string;
  name: string;
  path: string;
  src: string;
  steps: number;
  status: "ok" | "running" | "failed" | "pending";
  rows: string;
  elapsed: string;
  dotColor?: string;
}

const rows: PipelineRow[] = [
  { idx: "01", name: "Orders — nightly cohort",     path: "./out/cohort_report.json", src: "json_file", steps: 6, status: "ok",      rows: "128,412", elapsed: "1.83s" },
  { idx: "02", name: "Marketing spend rollup",       path: "./out/roi.json",           src: "csv_file",  steps: 4, status: "running", rows: "—",       elapsed: "00:07", dotColor: "var(--gold)" },
  { idx: "03", name: "Refunds — anomaly sweep",      path: "./out/flagged.json",       src: "json_file", steps: 9, status: "failed",  rows: "—",       elapsed: "0.31s", dotColor: "var(--red)" },
  { idx: "04", name: "Session — funnel joins",       path: "./out/funnel.json",        src: "json_file", steps: 12, status: "pending", rows: "—",     elapsed: "—",     dotColor: "var(--subtle)" },
];

const columns: Column<PipelineRow>[] = [
  { key: "idx",    header: "#",           width: "24px",  render: (r) => <span className="font-mono text-[10.5px] text-subtle">{r.idx}</span> },
  { key: "name",   header: "Name",        width: "2.2fr", render: (r) => (
    <div className="flex items-center gap-2.5 min-w-0">
      <span className="size-1.5 rounded-full shrink-0" style={{ background: r.dotColor ?? "var(--accent)" }} />
      <span className="font-medium truncate">{r.name}</span>
      <span className="font-mono text-[11px] text-subtle ml-1.5 truncate">{r.path}</span>
    </div>
  ) },
  { key: "src",    header: "Source",       width: "100px", render: (r) => <span className="font-mono text-[12px] text-muted">{r.src}</span> },
  { key: "steps",  header: "Steps",        width: "90px",  render: (r) => <span className="font-mono text-[12px] text-muted">{r.steps}</span> },
  { key: "status", header: "Status",       width: "120px", render: (r) => <Pill status={r.status} /> },
  { key: "rows",   header: "Rows",         width: "120px", render: (r) => <span className="font-mono text-[12px] font-medium text-text">{r.rows}</span> },
  { key: "elap",   header: "Elapsed",      width: "100px", render: (r) => <span className="font-mono text-[12px] text-subtle">{r.elapsed}</span> },
  { key: "more",   header: "",             width: "32px",  align: "center", render: () => <span className="text-subtle hover:text-text">⋯</span> },
];

const Divider = ({ label }: { label: string }) => (
  <div className="flex items-center gap-3.5 my-6 font-mono text-[10.5px] tracking-[0.3em] uppercase text-subtle">
    <span className="flex-1 h-px bg-border" />
    {label}
    <span className="flex-1 h-px bg-border" />
  </div>
);

export default function Preview() {
  return (
    <div className="grid grid-cols-[220px_1fr] min-h-screen">
      <Sidebar>
        <Brand version="v0.1" />
        <NavSearch />
        <NavSections>
          <NavGroup>Workspace</NavGroup>
          <NavItem href="#" label="Pipelines" active count={14} />
          <NavItem href="#" label="Runs" count={312} />
          <NavItem href="#" label="Sources" count={8} />
          <NavItem href="#" label="Schedules" count={6} />
          <NavGroup>System</NavGroup>
          <NavItem href="#" label="Engine" />
          <NavItem href="#" label="Design" />
          <NavItem href="#" label="Settings" />
        </NavSections>
        <NavFooter />
      </Sidebar>

      <main>
        <Topbar
          crumbs={[
            { label: "Workspace", href: "#" },
            { label: "Preview" },
          ]}
          actions={
            <>
              <Button variant="ghost" size="sm">Docs</Button>
              <Button size="sm" kbd="I">Import</Button>
              <Button variant="primary" size="sm" kbd="N">New pipeline</Button>
              <ThemeToggle />
            </>
          }
        />

        <PageHeader
          title="Component gallery"
          sub="/preview"
          lede="Every DTE UI primitive rendered in isolation. Toggle theme to sanity-check contrast."
          actions={<Button size="sm">Filter</Button>}
        />

        <div className="px-14 py-8 space-y-10">
          {/* BUTTONS */}
          <section>
            <SectionHead title="Buttons" count="· 3 variants × 2 sizes" />
            <div className="flex flex-wrap gap-3 items-center">
              <Button>Default</Button>
              <Button variant="primary">Primary</Button>
              <Button variant="ghost">Ghost</Button>
              <Button size="sm">Small</Button>
              <Button variant="primary" size="sm" kbd="⌘S">Save</Button>
              <Button size="sm" disabled>Disabled</Button>
            </div>
          </section>

          {/* PILLS */}
          <section>
            <SectionHead title="Status pills" count="· 4 states" />
            <div className="flex flex-wrap gap-3 items-center">
              <Pill status="ok" />
              <Pill status="running" />
              <Pill status="failed" />
              <Pill status="pending" />
            </div>
          </section>

          {/* METRICS */}
          <section>
            <SectionHead title="Metrics" count="· MetricRow + Metric" />
            <MetricRow>
              <Metric label="Rows written" value="128,412" tone="ok" />
              <Metric label="Elapsed"      value="1.83"    unit="s" />
              <Metric label="Started"      value={<span className="text-[18px]">03 Jul · 02:00:04</span>} />
              <Metric label="Engine"       value={<span className="text-[18px]">DuckDB 1.1.3</span>} />
            </MetricRow>
          </section>

          {/* TABLE */}
          <section>
            <SectionHead
              title="DataTable"
              count="· pipelines example"
              actions={<Button variant="ghost" size="sm">Refresh</Button>}
            />
            <DataTable columns={columns} rows={rows} onRowClick={() => {}} />
          </section>

          {/* STEPS */}
          <section>
            <SectionHead title="Step rows" count="· inside a Panel" />
            <div className="grid grid-cols-[1.4fr_1fr] gap-5">
              <Panel>
                <PanelHead label="Ordered steps" count={4} />
                <StepRow index={1} op="filter" title="Only completed orders">
                  <ExprCode>
                    <ExprToken as="field">status</ExprToken>{" "}
                    <ExprToken as="op">==</ExprToken>{" "}
                    <ExprToken as="value">&quot;completed&quot;</ExprToken>{" "}
                    <ExprToken as="op">AND</ExprToken>{" "}
                    <ExprToken as="field">amount</ExprToken>{" "}
                    <ExprToken as="op">&gt;</ExprToken>{" "}
                    <ExprToken as="value">0</ExprToken>
                  </ExprCode>
                </StepRow>
                <StepRow index={2} op="rename" title="Normalize field names">
                  <KV>
                    <KVItem label="customer_id" value="→ user_id" />
                    <KVItem label="order_ts" value="→ created_at" />
                    <KVItem label="amt_usd" value="→ amount" />
                  </KV>
                </StepRow>
                <StepRow index={3} op="map · lookup" title="Country → region">
                  <KV>
                    <KVItem label="field" value="country" />
                    <KVItem label="default" value={<>&quot;OTHER&quot;</>} />
                    <KVItem label="entries" value="4" />
                  </KV>
                </StepRow>
                <StepRow index={4} op="aggregate" title="Roll up by region + cohort week">
                  <KV>
                    <KVItem label="group_by" value="region, cohort_week" />
                    <KVItem label="sum" value="(amount) → gmv" />
                    <KVItem label="count_distinct" value="(user_id) → buyers" />
                  </KV>
                </StepRow>
                <AddStep />
              </Panel>

              {/* SIDE */}
              <div className="flex flex-col gap-4">
                <Panel>
                  <PanelHead label="Sources" count={2} />
                  <Item
                    glyph="§"
                    label="orders"
                    path="s3://acme-raw/orders/2026-07-03/*.json"
                    tag={<Tag>json</Tag>}
                  />
                  <Item
                    glyph="§"
                    label="region_lookup"
                    path="./ref/country_to_region.csv"
                    tag={<Tag>csv</Tag>}
                  />
                </Panel>
                <Panel>
                  <PanelHead label="Output" count={1} />
                  <Item
                    glyph="¶"
                    label="cohort_report"
                    path="./out/cohort_report.json"
                    tag={<Tag variant="output">json</Tag>}
                  />
                </Panel>
              </div>
            </div>
          </section>

          {/* TIMELINE */}
          <section>
            <SectionHead title="Timeline" count="· run events" />
            <Timeline>
              <TimelineRow time="02:00:04.112" message={<>Loaded source <InlineCode>orders</InlineCode> — 412,908 rows</>} duration="+0.31s" />
              <TimelineRow time="02:00:04.421" message={<>Step 1 · <InlineCode>filter</InlineCode> — retained 388,201</>} duration="+0.09s" />
              <TimelineRow tone="warn" time="02:00:04.569" message={<>Step 4 · <InlineCode>map</InlineCode> — 812 rows fell to default &quot;OTHER&quot;</>} duration="+0.12s" />
              <TimelineRow time="02:00:04.691" message={<>Step 5 · <InlineCode>aggregate</InlineCode> — 128,412 groups emitted</>} duration="+0.98s" />
              <TimelineRow tone="err" time="02:00:05.674" message={<>(demo) failure — <InlineCode>sort</InlineCode> tone example</>} duration="+0.21s" />
            </Timeline>
          </section>

          <Divider label="palette" />

          {/* PALETTE */}
          <section>
            <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
              {[
                { name: "surface", var: "var(--surface)" },
                { name: "text",    var: "var(--text)" },
                { name: "accent",  var: "var(--accent)" },
                { name: "gold",    var: "var(--gold)" },
                { name: "green",   var: "var(--green)" },
                { name: "red",     var: "var(--red)" },
              ].map(({ name, var: v }) => (
                <div
                  key={name}
                  className="border border-border rounded-[var(--radius)] aspect-[1/0.95] p-3 flex flex-col justify-between font-mono text-[10.5px]"
                  style={{ background: v }}
                >
                  <span className="uppercase tracking-[0.15em] font-bold" style={{ mixBlendMode: "difference", color: "#fff" }}>
                    {name}
                  </span>
                  <span style={{ mixBlendMode: "difference", color: "#fff" }}>{v}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
